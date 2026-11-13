"""Build the monthly point-in-time panel: price features, fundamental features, forward excess returns vs SPY."""
import json, sys, multiprocessing as mp
import numpy as np, pandas as pd
from common import *
from fundamentals import load_ticker

STALE_DAYS = 550
PRICE_FEATS = ["mom_12_1", "mom_6_1", "mom_3", "rev_1m", "dd_52w", "trend40", "vol_1y", "beta_2y", "mom_36_12", "mdd_3y"]
FUND_RAW = ["ey", "fcfy", "sy", "bm", "roe", "roic", "gm", "om", "om_stab", "om_trend", "rev_g1", "rev_g3", "rev_accel",
            "sue", "lev", "intcov", "dil_1y", "dil_3y", "accruals"]
REL_FEATS = ["ey_vs_hist", "fcfy_vs_hist", "ey_vs_sector", "fcfy_vs_sector"]

def sic_sector(sic):
    try: s = int(sic)
    except Exception: return "Other"
    if 100 <= s < 1000: return "Staples"
    if 1000 <= s < 1300 or 1400 <= s < 1500: return "Materials"
    if 1300 <= s < 1400 or 2900 <= s < 3000: return "Energy"
    if 1500 <= s < 1800: return "Industrials"
    if 2000 <= s < 2200: return "Staples"
    if 2830 <= s < 2840 or 3840 <= s < 3860 or 8000 <= s < 8100 or 8730 <= s < 8735: return "Health"
    if 2840 <= s < 2850: return "Staples"
    if 2200 <= s < 2400 or 2500 <= s < 2600 or 3140 <= s < 3200 or 3630 <= s < 3640 or 3710 <= s < 3720 or 3940 <= s < 3950: return "Discretionary"
    if 2400 <= s < 2700 or 2800 <= s < 2900 or 3000 <= s < 3500 and not (3400 <= s < 3500): return "Materials"
    if 3570 <= s < 3580 or 3600 <= s < 3700 or 3820 <= s < 3830 or 7370 <= s < 7380: return "Tech"
    if 3400 <= s < 3900: return "Industrials"
    if 4000 <= s < 4800: return "Industrials"
    if 4800 <= s < 4900 or 2700 <= s < 2800 or 7800 <= s < 7900: return "Communication"
    if 4900 <= s < 5000: return "Utilities"
    if 5000 <= s < 5200: return "Industrials"
    if 5200 <= s < 6000: return "Discretionary" if not (5400 <= s < 5500 or 5910 <= s < 5913) else "Staples"
    if 6798 <= s < 6799 or 6500 <= s < 6600: return "RealEstate"
    if 6000 <= s < 7000: return "Financials"
    if 7000 <= s < 8000: return "Discretionary" if s < 7300 or s >= 7900 else "Industrials"
    return "Other"

def load_prices(t):
    f = PRICES / f"{t}.parquet"
    if not f.exists(): return None
    d = pd.read_parquet(f)
    d = d[d.close > 0]
    return d if len(d) > 30 else None

def weekly(d):
    w = d[["adj", "close"]].resample("W-FRI").last().dropna()
    if len(w) and w.index[-1] > d.index[-1]:   # label the in-progress week by its latest trading day (matches Yahoo's live weekly bar)
        w.index = w.index[:-1].append(pd.DatetimeIndex([d.index[-1]]))
    return w

def price_features_weekly(w, spy_w):
    a = w["adj"]
    f = pd.DataFrame(index=w.index)
    f["mom_12_1"] = a.shift(4) / a.shift(52) - 1
    f["mom_6_1"] = a.shift(4) / a.shift(26) - 1
    f["mom_3"] = a / a.shift(13) - 1
    f["rev_1m"] = a / a.shift(4) - 1
    f["dd_52w"] = a / a.rolling(52, min_periods=40).max() - 1
    f["trend40"] = a / a.rolling(40, min_periods=30).mean() - 1
    r = np.log(a).diff()
    f["vol_1y"] = r.rolling(52, min_periods=40).std() * np.sqrt(52)
    rs = np.log(spy_w["adj"]).diff().reindex(r.index)
    cov = r.rolling(104, min_periods=52).cov(rs); var = rs.rolling(104, min_periods=52).var()
    f["beta_2y"] = cov / var
    f["mom_36_12"] = a.shift(52) / a.shift(156) - 1
    roll_max = a.rolling(156, min_periods=100).max()
    dd = a / a.cummax()  # placeholder replaced below
    # max drawdown over trailing 156 weeks
    arr = a.values; mdd = np.full(len(arr), np.nan)
    for i in range(100, len(arr)):
        seg = arr[max(0, i - 155):i + 1]
        mdd[i] = (seg / np.maximum.accumulate(seg) - 1).min()
    f["mdd_3y"] = mdd
    for k, v in tail_features_weekly(a, spy_w["adj"]).items(): f[k] = v
    return f

def tail_features_weekly(a, spy_a):
    """v3 tail features from weekly adjusted closes (see docs/PREREGISTRATION_V3.md section 3)."""
    out = {}
    r = np.log(a).diff(); rs = np.log(spy_a).diff().reindex(r.index)
    m = (rs < 0).astype(float).where(r.notna() & rs.notna(), 0.0)
    x = rs.fillna(0) * m; y = r.fillna(0) * m
    W = 104
    n = m.rolling(W, min_periods=52).sum()
    sx = x.rolling(W, min_periods=52).sum(); sy = y.rolling(W, min_periods=52).sum()
    sxy = (x * y).rolling(W, min_periods=52).sum(); sxx = (x * x).rolling(W, min_periods=52).sum()
    cov = (sxy - sx * sy / n) / (n - 1); var = (sxx - sx * sx / n) / (n - 1)
    out["beta_down"] = (cov / var).where((n >= 20) & (var > 0))
    sr = a / a.shift(1) - 1
    out["cvar_5"] = sr.rolling(52, min_periods=40).apply(lambda v: np.sort(v[~np.isnan(v)])[:3].mean(), raw=True)
    out["sigma_down"] = np.sqrt(52.0) * np.sqrt((np.minimum(sr, 0.0) ** 2).rolling(52, min_periods=40).mean())
    out["sma40_below"] = (a < a.rolling(40, min_periods=30).mean()).astype(float).where(a.rolling(40, min_periods=30).mean().notna())
    return out

def daily_features(d):
    """v3 daily features: VCP ratio and 50-day up/down dollar-volume ratio."""
    lr = np.log(d["adj"]).diff()
    vcp = lr.rolling(20, min_periods=20).std() / lr.rolling(120, min_periods=100).std()
    ret = d["adj"].pct_change(); dv = d["close"] * d["vol"].astype(float)
    up = (dv * (ret > 0)).rolling(50, min_periods=50).sum(); dn = (dv * (ret < 0)).rolling(50, min_periods=50).sum()
    return pd.DataFrame({"vcp_ratio": vcp, "up_down_vol_50d": (up / dn).where(dn > 0)})

def filing_drift(d, filed, dates):
    """post_filing_drift at each date: return over the first 5 trading days on/after the latest quarterly
    filing f (vs the close before f) times the volume surge vs the prior 50 days. Needs f+7d <= t, t-f <= 120d."""
    idx = d.index.values.astype("datetime64[ns]"); adj = d["adj"].values; vol = d["vol"].values.astype(float)
    per = {}
    for f in filed:
        i0 = np.searchsorted(idx, f, side="left")
        if i0 < 50 or i0 + 4 >= len(idx): continue
        base = vol[i0 - 50:i0].mean()
        if not (base > 0) or not (adj[i0 - 1] > 0): continue
        per[f] = (adj[i0 + 4] / adj[i0 - 1] - 1) * (vol[i0:i0 + 5].mean() / base)
    out = []
    fs = np.array(sorted(per), dtype="datetime64[ns]")
    for t in dates:
        tt = np.datetime64(t, "ns")
        j = np.searchsorted(fs, tt - np.timedelta64(7, "D"), side="right") - 1
        if j < 0 or (tt - fs[j]) > np.timedelta64(120, "D"): out.append(np.nan)
        else: out.append(per[fs[j]])
    return out

def month_ends(start="2001-01-31"):
    end = pd.Timestamp.today().normalize()
    m = pd.date_range(start, end, freq="ME")
    return list(m)

def fwd_excess(d, spy, dates, months):
    """(1+r_stock)/(1+r_spy)-1 from t to t+h. If the stock stops trading before t+h, proceeds are assumed
    to sit in SPY from its last price (excess frozen). NaN if t+h is in the future."""
    a = d["adj"]; s = spy["adj"]; last_spy = s.index[-1]; last_stock = a.index[-1]
    out = {}
    for h in months:
        vals = []
        for t in dates:
            t2 = t + pd.DateOffset(months=h)
            if t2 > last_spy: vals.append(np.nan); continue
            p0 = a.asof(t); s0 = s.asof(t)
            if np.isnan(p0) or a.index[0] > t: vals.append(np.nan); continue
            te = min(t2, last_stock) if last_stock < t2 else t2
            p1 = a.asof(te); s1 = s.asof(te)
            vals.append((p1 / p0) / (s1 / s0) - 1)
        out[f"y{h}"] = vals
    return pd.DataFrame(out, index=dates)

def fund_features(t, F, close_t, split_after):
    """Fundamental features at date t given PIT accessors F, split-adjusted close, split factor fn."""
    res = {}
    def v(k):
        e, x = F[k].at(t)
        if e is None or (t - pd.Timestamp(e)).days > STALE_DAYS: return None, np.nan
        return e, x
    e_rev, rev = v("rev"); e_ni, ni = v("ni"); e_eb, ebit = v("ebit"); _, gp = v("gp")
    _, cfo = v("cfo"); _, capex = v("capex"); _, ie = v("intexp")
    e_as, assets = v("assets"); _, eq = v("equity"); _, cash = v("cash"); _, ltd = v("ltdebt"); _, std = v("stdebt")
    _, ca = v("ca") if "ca" in F else (None, np.nan); _, cl = v("cl") if "cl" in F else (None, np.nan)
    e_sh, sh = v("shares")
    if np.isnan(sh): return None, {}
    sh_adj = sh * split_after(pd.Timestamp(e_sh))
    mcap = close_t * sh_adj
    debt = np.nansum([ltd, std]) if not (np.isnan(ltd) and np.isnan(std)) else 0.0
    cash0 = 0.0 if np.isnan(cash) else cash
    ev = mcap + debt - cash0
    if not (mcap > 0): return None, {}
    fcf = cfo - (0 if np.isnan(capex) else capex)
    res["ey"] = ebit / ev if ev > 0 else np.nan
    res["fcfy"] = fcf / mcap
    res["sy"] = rev / ev if ev > 0 else np.nan
    res["bm"] = eq / mcap
    res["roe"] = ni / eq if eq and eq > 0 else np.nan
    ic = (eq if not np.isnan(eq) else 0) + debt - cash0
    res["roic"] = ebit / ic if ic > 0 else np.nan
    res["gm"] = gp / rev if rev and rev > 0 else np.nan
    res["om"] = ebit / rev if rev and rev > 0 else np.nan
    # trends from the TTM history known at t
    if e_rev is not None:
        rev4 = F["rev"].near(e_rev - np.timedelta64(365, "D"), t); rev12 = F["rev"].near(e_rev - np.timedelta64(1095, "D"), t)
        res["rev_g1"] = rev / rev4 - 1 if rev4 and rev4 > 0 else np.nan
        res["rev_g3"] = (rev / rev12) ** (1 / 3) - 1 if rev12 and rev12 > 0 and rev > 0 else np.nan
        e_prev = e_rev - np.timedelta64(91, "D")
        r_prev = F["rev"].near(e_prev, t); r_prev4 = F["rev"].near(e_prev - np.timedelta64(365, "D"), t)
        g_prev = r_prev / r_prev4 - 1 if r_prev4 and r_prev4 > 0 else np.nan
        res["rev_accel"] = res["rev_g1"] - g_prev
    if e_eb is not None and e_rev is not None:
        oms = []
        for k in range(0, 12):
            ee = e_eb - np.timedelta64(91 * k, "D")
            eb_k = F["ebit"].near(ee, t, tol=30); rv_k = F["rev"].near(ee, t, tol=30)
            oms.append(eb_k / rv_k if rv_k and rv_k > 0 else np.nan)
        oms = np.array(oms)
        if np.sum(~np.isnan(oms)) >= 6: res["om_stab"] = -np.nanstd(oms)
        if not np.isnan(oms[0]) and len(oms) > 4 and not np.isnan(oms[4]): res["om_trend"] = oms[0] - oms[4]
    # earnings surprise proxy: standardized YoY change in quarterly net income (SUE, seasonal random walk)
    if F["ni_q"].ok:
        eq_, nq = F["ni_q"].at(t)
        if eq_ is not None and (t - pd.Timestamp(eq_)).days < 200:
            diffs = []
            for k in range(0, 9):
                ee = eq_ - np.timedelta64(91 * k, "D")
                a1 = F["ni_q"].near(ee, t, tol=30); a0 = F["ni_q"].near(ee - np.timedelta64(365, "D"), t, tol=30)
                diffs.append(a1 - a0)
            diffs = np.array(diffs)
            if not np.isnan(diffs[0]) and np.sum(~np.isnan(diffs[1:])) >= 4:
                sd = np.nanstd(diffs[1:])
                res["sue"] = np.clip(diffs[0] / sd, -10, 10) if sd > 0 else np.nan
    res["lev"] = debt / assets if assets and assets > 0 else np.nan
    res["intcov"] = np.log1p(np.clip(ebit / ie, -1 + 1e-9, 1000)) if ie and ie > 0 and not np.isnan(ebit) else np.nan
    sh4 = F["shares"].near(pd.Timestamp(e_sh).to_datetime64() - np.timedelta64(365, "D"), t, tol=60)
    sh12 = F["shares"].near(pd.Timestamp(e_sh).to_datetime64() - np.timedelta64(1095, "D"), t, tol=60)
    def adj(e_off):
        return split_after(pd.Timestamp(e_sh) - pd.Timedelta(days=e_off))
    res["dil_1y"] = sh_adj / (sh4 * adj(365)) - 1 if sh4 and sh4 > 0 else np.nan
    res["dil_3y"] = sh_adj / (sh12 * adj(1095)) - 1 if sh12 and sh12 > 0 else np.nan
    res["accruals"] = (ni - cfo) / assets if assets and assets > 0 else np.nan
    res["gpa"] = gp / assets if assets and assets > 0 else np.nan
    res["roa"] = ni / assets if assets and assets > 0 else np.nan
    res["mcap"] = mcap
    # ---- v3 additions (docs/PREREGISTRATION_V3.md section 3) ----
    res["fcf_conv"] = fcf / max(ni, 1e-6) if not (np.isnan(fcf) or np.isnan(ni)) else np.nan
    res["fcfy_ev"] = fcf / ev if ev > 0 else np.nan
    res["rule_of_40"] = res.get("rev_g1", np.nan) + (fcf / rev if rev and rev > 0 else np.nan)
    res["eq_assets"] = eq / assets if assets and assets > 0 else np.nan
    v4_features(res, F, t, v, e_rev, e_eb, e_as, rev, gp, ebit, eq, debt, cash0, fcf, mcap)
    res["f_score"] = piotroski(F, t, e_rev, e_as, ni, cfo, assets, ltd, ca, cl, gp, rev, res.get("dil_1y", np.nan))
    raw = dict(rev=rev, gp=gp, ebit=ebit, ni=ni, cfo=cfo, capex=capex, intexp=ie, assets=assets, equity=eq, cash=cash0,
               debt=debt, shares_adj=sh_adj, mcap=mcap, ca=ca, cl=cl, non_op=res.get("non_op_inv"))
    return raw, res

def v4_features(res, F, t, v, e_rev, e_eb, e_as, rev, gp, ebit, eq, debt, cash0, fcf, mcap):
    """v4 additions (docs/PREREGISTRATION_V4.md section 3)."""
    yr = np.timedelta64(365, "D")
    ago = lambda k, e, days=365: F[k].near(pd.Timestamp(e).to_datetime64() - np.timedelta64(days, "D"), t) if (e is not None and k in F) else np.nan
    nzv = lambda x: 0.0 if (x is None or np.isnan(x)) else x
    _, lt = v("inv_lt"); _, em = v("inv_em"); _, st = v("inv_st")
    non_op = nzv(lt) + nzv(em) + nzv(st)
    res["non_op_inv"] = non_op
    adj_ev = max(mcap + debt - cash0 - non_op, 0.25 * mcap)
    res["fcfy_adj_ev"] = fcf / adj_ev if not np.isnan(fcf) else np.nan
    res["ey_adj_ev"] = ebit / adj_ev if not np.isnan(ebit) else np.nan
    # incremental ROIC over 3 years
    if e_eb is not None and e_as is not None:
        eb3 = ago("ebit", e_eb, 1095); eq3 = ago("equity", e_as, 1095)
        d3 = nzv(ago("ltdebt", e_as, 1095)) + nzv(ago("stdebt", e_as, 1095)); c3 = nzv(ago("cash", e_as, 1095))
        ic_now = (0 if np.isnan(eq) else eq) + debt - cash0
        ic3 = eq3 + d3 - c3 if not np.isnan(eq3) else np.nan
        dic = ic_now - ic3
        res["inc_roic_3y"] = (ebit - eb3) / dic if (not np.isnan(dic) and dic > 0 and not np.isnan(eb3) and not np.isnan(ebit)) else np.nan
    if e_rev is not None:
        rev1 = ago("rev", e_rev); gp1 = ago("gp", e_rev)
        gm0 = gp / rev if (rev and rev > 0 and not np.isnan(gp)) else np.nan
        gm1 = gp1 / rev1 if (rev1 and rev1 > 0 and not np.isnan(gp1)) else np.nan
        res["inc_gm"] = gm0 - gm1
        e_rd, rd = v("rd")
        rd1 = ago("rd", e_rd) if e_rd is not None else np.nan
        res["rd_roi"] = (rev - rev1) / rd1 if (rd1 and rd1 > 0 and not np.isnan(rev1)) else np.nan
        res["rd_int"] = rd / rev if (rev and rev > 0 and not np.isnan(rd)) else np.nan
    # deferred revenue / contract liabilities
    def dr_at(off):
        for keys in (("dr",), ("dr_c1", "dr_n1"), ("dr_c2", "dr_n2")):
            vals, ends = [], []
            for k in keys:
                if off == 0:
                    e, x = v(k)
                    if e is not None and not np.isnan(x): vals.append(x); ends.append(e)
            if off == 0 and vals: return sum(vals), ends[0], keys
        return np.nan, None, None
    dr, e_dr, keys = dr_at(0)
    if keys is not None:
        dr1 = sum(nzv(ago(k, e_dr)) for k in keys)
        res["def_rev_g1"] = dr / dr1 - 1 if dr1 > 0 else np.nan

def piotroski(F, t, e_rev, e_as, ni, cfo, assets, ltd, ca, cl, gp, rev, dil1):
    """9-point Piotroski F-score on TTM vs one year earlier; 9*points/available if >=5 tests available."""
    def ago(k, e):
        if e is None or k not in F: return np.nan
        return F[k].near(pd.Timestamp(e).to_datetime64() - np.timedelta64(365, "D"), t)
    a0 = ago("assets", e_as); ni0 = ago("ni", e_rev); rev0 = ago("rev", e_rev); gp0 = ago("gp", e_rev)
    ltd0 = ago("ltdebt", e_as); ca0 = ago("ca", e_as); cl0 = ago("cl", e_as)
    ok = lambda *xs: all(x is not None and not np.isnan(x) for x in xs)
    tests = []
    roa = ni / assets if ok(ni, assets) and assets > 0 else np.nan
    roa0 = ni0 / a0 if ok(ni0, a0) and a0 > 0 else np.nan
    tests.append(roa > 0 if ok(roa) else None)
    tests.append(cfo > 0 if ok(cfo) else None)
    tests.append(roa > roa0 if ok(roa, roa0) else None)
    tests.append(cfo > ni if ok(cfo, ni) else None)
    lv = ltd / assets if ok(ltd, assets) and assets > 0 else np.nan
    lv0 = ltd0 / a0 if ok(ltd0, a0) and a0 > 0 else np.nan
    tests.append(lv < lv0 if ok(lv, lv0) else None)
    cr = ca / cl if ok(ca, cl) and cl > 0 else np.nan
    cr0 = ca0 / cl0 if ok(ca0, cl0) and cl0 > 0 else np.nan
    tests.append(cr > cr0 if ok(cr, cr0) else None)
    tests.append(dil1 <= 0 if ok(dil1) else None)
    gm = gp / rev if ok(gp, rev) and rev > 0 else np.nan
    gm0 = gp0 / rev0 if ok(gp0, rev0) and rev0 > 0 else np.nan
    tests.append(gm > gm0 if ok(gm, gm0) else None)
    at = rev / assets if ok(rev, assets) and assets > 0 else np.nan
    at0 = rev0 / a0 if ok(rev0, a0) and a0 > 0 else np.nan
    tests.append(at > at0 if ok(at, at0) else None)
    av = [x for x in tests if x is not None]
    return 9.0 * sum(bool(x) for x in av) / len(av) if len(av) >= 5 else np.nan

def split_factor_fn(d):
    sp = d["split"]; sp = sp[sp != 1.0]
    def f(date):
        return float(np.prod(sp[sp.index > date].values)) if len(sp) else 1.0
    return f

def process(t, dates_str, want_targets=True):
    import warnings; warnings.filterwarnings("ignore")
    dates = [pd.Timestamp(x) for x in dates_str]
    d = load_prices(t)
    if d is None: return t, None, None
    spy = load_prices("SPY")
    w = weekly(d); spy_w = weekly(spy)
    pf = price_features_weekly(w, spy_w)
    rows = pf.reindex(pd.DatetimeIndex(dates), method="ffill", tolerance=pd.Timedelta(days=8))
    rows["px_close"] = d["close"].reindex(pd.DatetimeIndex(dates), method="ffill", tolerance=pd.Timedelta(days=8)).values
    rows["first_px"] = d.index[0]
    dfe = daily_features(d)
    dfe = dfe.reindex(pd.DatetimeIndex(dates), method="ffill", tolerance=pd.Timedelta(days=8))
    for c in dfe: rows[c] = dfe[c].values
    rows["last_px_ord"] = float((d.index[-1] - pd.Timestamp("1970-01-01")).days)
    if want_targets:
        y = fwd_excess(d, spy, dates, HORIZONS)
        rows = rows.join(y)
    F = None
    try: F = load_ticker(t)
    except Exception as e: F = None
    raws = {}
    if F is not None:
        sf = split_factor_fn(d)
        fr = []
        for dt in dates:
            c = rows.at[dt, "px_close"]
            if dt < pd.Timestamp("2009-06-30") or np.isnan(c): fr.append({}); continue
            raw, ff = fund_features(dt, F, c, sf)
            fr.append(ff); raws[dt] = raw
        fdf = pd.DataFrame(fr, index=rows.index)
        rows = rows.join(fdf)
        # valuation versus own history (trailing 60 months, min 24)
        for k in ("ey", "fcfy"):
            if k in rows:
                med = rows[k].rolling(60, min_periods=24).median()
                rows[f"{k}_hist_med"] = med
                rows[f"{k}_vs_hist"] = rows[k] - med
        # v3 rolling own-history features (60 month-ends, min 24)
        if "roic" in rows: rows["roic_5y_med"] = rows["roic"].rolling(60, min_periods=24).median()
        if "roe" in rows: rows["roe_stab"] = -rows["roe"].rolling(60, min_periods=24).std()
        if F.get("filed_q") is not None and len(F["filed_q"]):
            rows["post_filing_drift"] = filing_drift(d, F["filed_q"], dates)
    rows["ticker"] = t
    last_raw = raws[dates[-1]] if dates[-1] in raws else None
    return t, rows, last_raw

if __name__ == "__main__":
    tickers = [l.strip() for l in open(CACHE / "universe_all.txt") if l.strip()]
    dates = month_ends()
    asof = load_prices("SPY").index[-1]
    if dates[-1] < asof: dates.append(asof)
    else: dates[-1] = asof
    ds = [str(x.date()) for x in dates]
    with mp.Pool(8) as pool:
        res = pool.starmap(process, [(t, ds) for t in tickers])
    frames = [r[1] for r in res if r[1] is not None]
    panel = pd.concat(frames).reset_index().rename(columns={"index": "date"})
    # sectors
    sec = {}
    for t in tickers:
        f = EDGAR / f"{t}.sub.json"
        sec[t] = sic_sector(json.load(open(f)).get("sic")) if f.exists() else "Other"
    panel["sector"] = panel["ticker"].map(sec)
    # membership flag (as-of)
    mem = membership()
    md = mem["date"].values
    member = np.zeros(len(panel), dtype=bool)
    sets = [set(x) for x in mem["tickers"]]
    for i, (dt, tk) in enumerate(zip(panel["date"].values, panel["ticker"].values)):
        j = np.searchsorted(md, dt, side="right") - 1
        member[i] = j >= 0 and tk in sets[j]
    panel["member"] = member
    for k in ("ey", "fcfy"):
        med = panel[panel.member].groupby(["date", "sector"])[k].median().rename(f"{k}_sec_med")
        panel = panel.join(med, on=["date", "sector"])
        panel[f"{k}_vs_sector"] = panel[k] - panel[f"{k}_sec_med"]
    panel.to_parquet(CACHE / "panel.parquet")
    raws = {r[0]: r[2] for r in res if r[2] is not None}
    json.dump({k: {a: (None if (b is None or (isinstance(b, float) and np.isnan(b))) else float(b)) for a, b in v.items()} for k, v in raws.items()},
              open(CACHE / "latest_fundamentals.json", "w"))
    print(panel.shape, panel.member.sum(), panel.date.max())
