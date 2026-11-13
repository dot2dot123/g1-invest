"""G1 v4 page data. Writes gitignored cleartext JSON to build/data/: one shared bundle (any-ticker lookup data,
models, regime, dossier pool) and one isolated file per configured page (config/users.json).

  python build_site.py               full: shared bundle + every page
  python build_site.py --site-only   reuse build/data/shared.json, rebuild page files only (fast)
  python build_site.py --page SLUG   restrict page files to one slug (combine with --site-only for a <5 s user build)

Isolation: a page file only holds its own books, its own dossiers/earnings/weekly prices for those books, and Danelfin
fields only when that page has "danelfin": true. Definitions: docs/PREREGISTRATION_V4.md."""
import json, math, sys, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from common import *
import model_v2 as M2
import model_v4 as M4
import style as ST

PCT = np.linspace(0, 1, 101)
OUT = ROOT / "build" / "data"
LA = ZoneInfo("America/Los_Angeles")
SECTORS = ["Communication", "Discretionary", "Energy", "Financials", "Health", "Industrials", "Materials", "Other",
           "RealEstate", "Staples", "Tech", "Utilities"]
# Columns shipped per ticker (compact columnar rows). Price-dependent ones are recomputed in the browser on Refresh.
COLS = ["px", "mcap", "roic_5y_med", "inc_roic_3y", "fcf_conv", "gpa", "accruals", "dil_3y", "dil_1y", "roe", "roa", "roe_stab",
        "eq_assets", "bm", "fcfy", "ey", "ey_vs_hist", "fcfy_adj_ev", "ey_adj_ev", "om_trend", "sue", "rev_accel", "inc_gm",
        "rule_of_40", "def_rev_g1", "rd_roi", "post_filing_drift", "mom_12_1", "mom_6_1", "dd_52w", "vcp_ratio", "up_down_vol_50d",
        "lev", "intcov", "beta_down", "cvar_5", "f_score", "sma40_below", "sigma_down", "rev_1m", "trend40", "vol_1y", "beta_2y",
        "mdd_3y", "roic", "om_stab", "gm", "rev_g1", "rev_g3",
        # raw for live re-pricing
        "ebit", "cfo", "capex", "equity", "debt", "cash", "non_op", "shares_adj", "ey_hist_med", "fcfy_hist_med",
        # style history, stops
        "roe_med5", "roe_min5", "roa_min5", "sma40c", "ema10c",
        # v4.2: cyclically-adjusted value input, weekly volume/close quality for CLIMAX TRIM
        "fcfy_ev", "wk_vol_x", "wk_close_pos"]
PRICE_DEP = ["ey", "fcfy", "bm", "ey_vs_hist", "fcfy_adj_ev", "ey_adj_ev", "mcap", "fcfy_ev"]

def nz(v):
    try: f = float(v)
    except Exception: return None
    return None if (math.isnan(f) or math.isinf(f)) else f

def rnd(v, sig=6):
    v = nz(v)
    if v is None or v == 0: return v
    return float(f"{v:.{sig}g}")

def qpct(x, q):
    """Percentile of x within shipped quantiles q (101 points). Mirrors qpct() in app.js exactly."""
    if x is None or q is None: return None
    n = len(q)
    if x < q[0]: return 0.0
    if x > q[-1]: return 1.0
    lo = int(np.searchsorted(q, x, side="left")); hi = int(np.searchsorted(q, x, side="right")) - 1
    if lo <= hi: return (lo + hi) / 2 / (n - 1)
    a, b = hi, lo
    return (a + (x - q[a]) / (q[b] - q[a])) / (n - 1)

def quant(s):
    s = pd.to_numeric(s, errors="coerce").astype(float).dropna()
    return [rnd(x, 8) for x in np.quantile(s, PCT)] if len(s) >= 5 else None

def interp(x, xs, ys):
    """Mirrors interp() in app.js."""
    if x <= xs[0]: return ys[0]
    if x >= xs[-1]: return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]); return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]

def decile_table(df, col, y):
    o = df[["date", col, y]].dropna().copy()
    o["r"] = o.groupby("date")[col].rank(pct=True)
    o["dec"] = np.clip(np.ceil(o.r * 10) - 1, 0, 9)
    return [{"mid": (d + 0.5) / 10, "hit": float((g[y] > 0).mean()), "p10": float(g[y].quantile(.1)), "p50": float(g[y].median()),
             "p90": float(g[y].quantile(.9)), "n": int(len(g))} for d, g in o.groupby("dec")]

# ---------------- python mirror of the browser score (app.js scoreTicker) ----------------
def live_scores(f, sector, fin, M):
    """f: dict of shipped features. Returns A, sleeves, U, D, S_quant (current regime), S_price. Mirrors app.js."""
    sq = M["sq"].get(sector) or {}; sqA = M["sqA"].get(sector) or {}; uq = M["uq"]; fq = M["fq"]
    def r(name, q): return qpct(f.get(name), q) if q else None
    def sg(v, s): return 0.5 if v is None else (v if s > 0 else 1 - v)
    def mean(xs): return fsum_js(xs) / len(xs)
    g = dict(f)
    eyh = g.get("ey_vs_hist"); omt = g.get("om_trend")
    g["gated_ey_vs_hist"] = None if eyh is None else eyh * (1.0 if (omt is not None and omt >= 0) else 0.0)
    if fin:
        for k in M4.FIN_MASK: g[k] = None
    rs = lambda name: qpct(g.get(name), sq.get(name)) if sq.get(name) else None
    ru = lambda name: qpct(g.get(name), uq.get(name)) if uq.get(name) else None
    rf = lambda name: qpct(g.get(name), fq.get(name)) if fq.get(name) else None
    o = {}
    o["S1"] = mean([sg(rf(k), s) for k, s in M4.S1_FIN]) if fin else mean([sg(rs(k), s) for k, s in M4.S1])
    o["S2"] = mean([sg(rs(k), s) for k, s in M4.S2])
    o["S3"] = mean([sg(rs(k), s) for k, s in M4.S3])
    o["S4"] = mean([0.5 * sg(ru(k), s) + 0.5 * sg(rs(k), s) for k, s in M4.S4]) * M["smult"].get(sector, 1.0)
    f4 = 0.05 * (g.get("form4") or 0.0)
    o["S5"] = (mean([sg(rf(k), s) for k, s in M4.S5_FIN]) if fin else mean([sg(ru(k), s) for k, s in M4.S5])) + f4
    o["U"] = 100 * (0.35 * o["S3"] + 0.35 * o["S4"] + 0.30 * (o["S1"] + o["S2"]) / 2)
    o["D"] = 100 * (0.50 * o["S5"] + 0.30 * o["S1"] + 0.20 * o["S2"])
    w = M4.REGIME_W[M["regime"]]
    o["S_quant"] = w * o["U"] + (1 - w) * o["D"]
    sp = mean([sg(ru(k), s) for k, s in M4.SPRICE]) - 0.15 * (g.get("sma40_below") or 0.0)
    o["S_price"] = 100 * min(1.0, max(0.0, sp))
    # v2 composite A (within-sector, centred ranks; missing -> 0)
    pv = []
    for comps in M2.PILLARS.values():
        pv.append(fsum_js(s * ((qpct(f.get(n), sqA.get(n)) - 0.5) if (sqA.get(n) and f.get(n) is not None) else 0.0) for n, s in comps) / len(comps))
    o["A"] = fsum_js(pv) / len(pv)
    return o

# ---------------- v4.2 live score mirror (app.js v42Of) ----------------
BM_MAXPTS = {"durable_roe": 2, "low_leverage": 1, "stable_margins": 1, "consistent_profits": 1, "gross_margin": 2, "share_count": 1, "fcf_vs_treasury": 2}
def bm_static(f, tsy):
    """Mirror of app.js bmStatic(): Buffett & Munger rule points (sum 0-10)."""
    g = f.get; c = {}
    med, mn = g("roe_med5"), g("roe_min5")
    c["durable_roe"] = 1 if med is None else (2 if (med >= 0.15 and mn is not None and mn >= 0.10) else (1 if med >= 0.12 else 0))
    c["low_leverage"] = 0.5 if g("lev") is None else (1 if g("lev") <= 0.30 else 0)
    c["stable_margins"] = 0.5 if g("om_stab") is None else (1 if g("om_stab") >= -0.03 else 0)
    c["consistent_profits"] = 0.5 if g("roa_min5") is None else (1 if g("roa_min5") > 0 else 0)
    c["gross_margin"] = 1 if g("gm") is None else (2 if g("gm") >= 0.40 else (1 if g("gm") >= 0.25 else 0))
    c["share_count"] = 0.5 if g("dil_3y") is None else (1 if g("dil_3y") <= 0 else 0)
    fc = g("fcfy"); c["fcf_vs_treasury"] = 1 if fc is None else (2 if fc >= tsy else (1 if fc >= 0.6 * tsy else 0))
    return c

def l15_static(f, mq):
    """Mirror of app.js styleOf() lean Magic 15 (0-10)."""
    def sg(v, s): return 0.5 if v is None else (v if s > 0 else 1 - v)
    pills = [fsum_js([sg(qpct(f.get(n), mq.get(n)), s) for n, s in ST.MAGIC[k]]) / len(ST.MAGIC[k]) for k in ST.LEAN]
    return 10 * fsum_js(pills) / len(pills)

def v42_parts(f, sector, M):
    """Pillars P1-P4 and the blend (docs/PREREGISTRATION_V4_2.md); ranks against shipped build-date quantiles."""
    q = M["v42q"]; sqs = q["sec"].get(sector) or {}
    nz5 = lambda v: 0.5 if v is None else v
    bm = fsum_js(bm_static(f, M["tsy"]).values()); l15 = l15_static(f, M["mq"])
    p1 = nz5(qpct(bm, q["bm"])); p2 = nz5(qpct(l15, q["l15"]))
    p3 = (nz5(qpct(f.get("ey_hist_med"), sqs.get("ey_hist_med"))) + nz5(qpct(f.get("fcfy_ev"), sqs.get("fcfy_ev")))) / 2
    bd = qpct(f.get("beta_down"), q["beta_down"])
    p4 = (nz5(qpct(f.get("mom_12_1"), sqs.get("mom_12_1"))) + (0.5 if bd is None else 1 - bd)) / 2
    return {"bm": bm, "l15": l15, "P1": p1, "P2": p2, "P3": p3, "P4": p4, "blend": (p1 + p2 + p3 + p4) / 4}

def v42_score(parts, M):
    v = qpct(parts["blend"], M["v42q"]["blend"])
    if parts["bm"] < 4.0: v = min(v, 0.65)
    return 100 * v

def fsum_js(xs):
    """Left-to-right float sum like JS reduce (Python >= 3.12 sum() uses compensated summation, which differs in the last bits)."""
    acc = 0.0
    for x in xs: acc += x
    return acc

def calib(score, pq, cal):
    s = qpct(score, pq); mids = [c["mid"] for c in cal]
    out = {"pct": s}
    for k in ("hit", "p10", "p50", "p90"): out[k] = interp(s, mids, [c[k] for c in cal])
    return out

# ---------------- helpers for weekly/stops/earnings ----------------
def weekly_close(t):
    f = PRICES / f"{t}.parquet"
    if not f.exists(): return None
    d = pd.read_parquet(f)
    d = d[d.close > 0]
    return d[["adj", "close"]].resample("W-FRI").last().dropna()

def weekly_climax(t):
    """Last week's volume / median weekly volume of the prior 52 weeks, and where the last weekly close sits in that
    week's range (0 = low, 1 = high). The cache has daily closes only, so the weekly range is the range of daily closes
    (proxy); a live Refresh uses Yahoo's real weekly high/low/volume."""
    d = pd.read_parquet(PRICES / f"{t}.parquet")
    d = d[d.close > 0]
    if len(d) < 300 or "vol" not in d: return None, None
    wk = d.resample("W-FRI").agg({"close": ["last", "max", "min"], "vol": "sum"}).dropna()
    if len(wk) < 53: return None, None
    v = wk[("vol", "sum")].values; med = float(np.median(v[-53:-1]))
    hi, lo, cl = wk[("close", "max")].iloc[-1], wk[("close", "min")].iloc[-1], wk[("close", "last")].iloc[-1]
    return (float(v[-1] / med) if med > 0 else None), (float((cl - lo) / (hi - lo)) if hi > lo else 0.5)

def ema(xs, n=10):
    a = 2 / (n + 1); e = xs[0]
    for x in xs[1:]: e = a * x + (1 - a) * e
    return e

_EARN = None
def next_earnings(t, today):
    """Earliest (last 4 quarterly SEC filing dates + 364 days) that is >= today (pre-registered estimate).
    Cached per ticker in cache/earn_cache.json for the same day so single-page builds stay fast."""
    global _EARN
    f = CACHE / "earn_cache.json"
    if _EARN is None:
        _EARN = json.load(open(f)) if f.exists() else {}
    key = f"{t}|{today.date()}"
    if key in _EARN: return _EARN[key]
    v = _next_earnings(t, today)
    _EARN[key] = v
    try: json.dump(_EARN, open(f, "w"))
    except Exception: pass
    return v

def _next_earnings(t, today):
    try:
        from fundamentals import load_ticker
        F = load_ticker(t)
        fq = F.get("filed_q") if F else None
        if fq is None or not len(fq): return None
        c = sorted(pd.Timestamp(x) + pd.Timedelta(days=364) for x in fq[-4:])
        c = [x for x in c if x >= today]
        return str(c[0].date()) if c else None
    except Exception:
        return None

def py_verdict(sc, f, quant, bear=False):
    """Mirror of app.js verdict() without an Entry $ (so never CLIMAX TRIM). Used for the live audit ledger and QA."""
    P, sma, r1 = f.get("px"), f.get("sma40c"), f.get("rev_1m")
    below = (P < sma) if sma is not None else f.get("sma40_below") == 1
    above = (P > sma) if sma is not None else f.get("sma40_below") == 0
    Up, Sp = sc.get("Up", sc["U"]), sc.get("Sp", sc["D"])   # percentiles among the top-1000 (set by score_one)
    has_fund = sc.get("kind", "full") != "price"
    fund_ok = has_fund and quant >= 75 and Up >= 70 and Sp >= 60
    dd = f.get("dd_52w"); om = f.get("om_trend")
    if fund_ok and above and not (r1 is not None and r1 > 0.15): v = "STRONG BUY"
    elif fund_ok and above and r1 is not None and r1 > 0.15: v = "ACCUMULATE (Staggered)"
    elif has_fund and quant >= 70 and Up >= 65 and (below or (dd is not None and dd < -0.2)): v = "WAIT FOR TREND (Pullback)"
    elif below and (quant < 45 or (om is not None and om < 0 and quant < 70)): v = "SELL / BROKEN"
    else: v = "HOLD"
    if bear and v in ("STRONG BUY", "ACCUMULATE (Staggered)"): v += " (buys paused)"
    return v

def score_one(t, S):
    """Python mirror of the browser score for one shipped ticker -> (quant, sc dict, features)."""
    meta = S["meta"]; mt = S["tmeta"][t]
    f = dict(zip(meta["cols"], S["rows"][t])) | {"form4": mt[4]}
    sector = meta["sectors"][mt[0]]
    M = {k: meta[k] for k in ("sq", "sqA", "uq", "fq", "smult", "mq", "tsy", "v42q")} | {"regime": meta["weather"]["build_regime"]}
    sc = live_scores(f, sector, mt[2] == 1, M)
    if mt[1] == 1:
        sc["V42"] = v42_score(v42_parts(f, sector, M), M); model = meta["live"]
    else: model = "S_price"
    raw = sc[model]
    quant = 100 * qpct(raw, meta["pq"][model]) if model == "A" else raw
    sc["kind"] = "full" if mt[1] == 1 else "price"
    sc["Up"] = 100 * qpct(sc["U"], meta["pq"]["U"]); sc["Sp"] = 100 * qpct(sc["D"], meta["pq"]["D"])
    return quant, sc, f

def append_audit(S, tickers, pool):
    """Weekly live audit ledger (cache/live_audit.jsonl): one row per (ISO week, ticker), appended on manual builds only."""
    f = CACHE / "live_audit.jsonl"
    seen = set()
    if f.exists():
        for line in open(f):
            try: r = json.loads(line); seen.add((r["week"], r["ticker"]))
            except Exception: pass
    today = dt.datetime.now(LA).date(); iso = today.isocalendar(); week = f"{iso[0]}-W{iso[1]:02d}"
    W = S["meta"]["weather"]; bear = W["spy"] < W["sma40"] and W["breadth"] < 0.35
    n = 0
    with open(f, "a") as out:
        for t in sorted(tickers):
            if t not in S["rows"] or (week, t) in seen: continue
            q, sc, fe = score_one(t, S)
            d = pool.get(t) or {}
            out.write(json.dumps({"week": week, "date": str(today), "ticker": t, "quant_score": round(q, 2), "model": S["meta"]["live"],
                                  "dossier_score": d.get("f_strat"), "verdict": py_verdict(sc, fe, q, bear), "price": fe.get("px"),
                                  "price_asof": S["meta"]["price_asof"]}) + "\n")
            n += 1
    print("live audit:", n, "new rows for", week, "->", f.name)
    return n

def load_config(full=False):
    f = ROOT / "config" / "users.json"
    if not f.exists(): raise SystemExit("Missing config/users.json. Copy config/users.example.json and edit (see docs/REBUILD_GUIDE.md).")
    c = json.load(open(f))
    return c if full else c["pages"]

def proxy_url():
    """Optional own CORS proxy (workers/cors-proxy.js). Env G1_PROXY_URL wins over users.json "proxy_url"; empty = free proxies only."""
    import os
    return (os.environ.get("G1_PROXY_URL") or load_config(True).get("proxy_url") or "").strip()

def read_book(path, danelfin):
    d = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in d.columns}
    if "ticker" not in cols:  # headerless "Ticker" or "Ticker,Shares[,Cost]" file
        d = pd.read_csv(path, header=None); d.columns = ["Ticker", "Shares", "Cost"][:d.shape[1]]
        cols = {c.lower(): c for c in d.columns}
    rows = []
    for _, r in d.iterrows():
        t = str(r[cols["ticker"]]).strip().upper().replace("-", ".")
        if not t or t == "NAN": continue
        g = lambda k: nz(r[cols[k]]) if k in cols else None
        row = {"t": t, "name": (str(r[cols["company"]]) if "company" in cols and isinstance(r[cols["company"]], str) else None),
               "shares": g("shares"), "entry": next((g(k) for k in ("entryprice", "entry price", "entry", "purchase price", "cost") if k in cols), None)}
        if danelfin:
            row.update({"ai": g("ai score"), "fund": g("fundamental"), "tech": g("technical"), "sent": g("sentiment"), "lowrisk": g("low risk")})
        rows.append(row)
    return rows

# ---------------- shared bundle ----------------
def shared():
    p2 = pd.read_parquet(CACHE / "panel_v2.parquet")
    now = p2.date.max()
    cur = p2[(p2.date == now) & p2.px_close.notna()].copy().set_index("ticker")
    cur["form4"], f4_last = M4.form4_cluster(cur.reset_index())
    U = cur[cur.univ].copy()
    res4 = {int(k) if k.isdigit() else k: v for k, v in json.load(open(CACHE / "model_v4_results.json")).items()}
    passed = bool(res4["pass"]["PASS"])
    res42 = {int(k) if k.isdigit() else k: v for k, v in json.load(open(CACHE / "model_v42_results.json")).items()}
    passed42 = bool(res42["pass"]["PASS"])
    live = "V42" if passed42 else ("S_quant" if passed else "A")
    # regime + market weather
    fred, spy = M4.load_macro()
    rg = M4.regime_at(now, fred, spy)
    breadth = float((U.sma40_below.dropna() == 0).mean())
    # weekly breadth over 26 weeks for the current top-1000 (capitulation rule)
    closes = {}
    for t in U.index:
        w = weekly_close(t)
        if w is not None: closes[t] = w["adj"].iloc[-80:]
    W = pd.DataFrame(closes).sort_index()
    sma = W.rolling(40, min_periods=30).mean()
    above = (W > sma).astype(float).where(sma.notna() & W.notna())
    wb = (above.sum(axis=1) / above.notna().sum(axis=1).replace(0, np.nan)).dropna().iloc[-14:]
    hy = fred["BAMLH0A0HYM2"].dropna()
    cv = fred["T10Y2Y"].dropna()
    spy_w = weekly_close("SPY")["adj"]
    spy_d = pd.read_parquet(PRICES / "SPY.parquet")["adj"].dropna()
    rr = spy_d.pct_change().dropna().iloc[-252:]
    spy_dvol = float(np.sqrt(252 * np.mean(np.minimum(rr.values, 0.0) ** 2)))
    weather = {"hy": nz(hy.iloc[-1]), "hy_date": str(hy.index[-1].date()), "hy_peak13": nz(hy[hy.index > hy.index[-1] - pd.Timedelta(days=91)].max()),
               "curve": nz(cv.iloc[-1]), "curve_date": str(cv.index[-1].date()), "breadth": breadth,
               "breadth_min13": nz(wb.iloc[:-1].min()), "breadth_weekly_now": nz(wb.iloc[-1]),
               "build_regime": rg["regime"], "spy": rg["spy"], "sma40": rg["sma40"], "spy_hi52": nz(spy_w.iloc[-52:].max()),
               "form4_last": str(pd.Timestamp(f4_last).date()) if f4_last is not None else None,
               "spy_dvol": spy_dvol, "eq_vm": min(1.0, max(0.5, 0.14 / spy_dvol)) if spy_dvol > 0 else 1.0}
    # sector multipliers at build (S4)
    sm = M4.sector_mult(U.reset_index().assign(date=now))
    smult = {s: float(m) for s, m in zip(U.sector.values, sm)}
    # masked copy for quantiles (financials override)
    Uq = U.copy(); fin = M4.is_fin(Uq["sic"]); Uq["gated_ey_vs_hist"] = Uq.ey_vs_hist * (Uq.om_trend >= 0).astype(float)
    for k in M4.FIN_MASK: Uq.loc[fin, k] = np.nan
    sec_feats = sorted({f for f, _ in M4.S1 + M4.S2 + M4.S3 + M4.S4})
    sq = {s_: {f: quant(g[f]) for f in sec_feats} for s_, g in Uq.groupby("sector")}          # v4 (financials masked)
    sqA = {s_: {f: quant(g[f]) for f in M2.A_FEATS} for s_, g in U.groupby("sector")}         # v2 composite A (unmasked)
    uq = {f: quant(Uq[f]) for f in sorted({f for f, _ in M4.S4 + M4.S5 + M4.SPRICE})}
    fq = {f: quant(Uq.loc[fin, f]) for f in sorted({f for f, _ in M4.S1_FIN + M4.S5_FIN})}
    mq = {f: quant(U[f]) for f in ST.MAGIC_FEATS}
    # style history (B&M) for every ticker
    ph = ST.add_hist(p2[p2.date >= now - pd.DateOffset(months=62)])
    hist = ph[ph.date == now].set_index("ticker")[["roe_med5", "roe_min5", "roa_min5"]]
    cur = cur.join(hist)
    # raw fundamentals + stops
    raw = json.load(open(CACHE / "latest_fundamentals_v2.json"))
    names, by_cik = {}, {}
    try:
        for v in json.load(open(CACHE / "company_tickers.json")).values():
            tk = v["ticker"].replace("-", "."); names.setdefault(tk, v["title"]); by_cik.setdefault(int(v["cik_str"]), []).append(tk)
    except Exception: pass
    spcur = json.load(open(CACHE / "sp500_current.json"))
    rows, meta_t = {}, {}
    for t, r in cur.iterrows():
        rw = raw.get(t) or {}
        w = weekly_close(t)
        sma40c = ema10c = wk_vol_x = wk_close_pos = None
        if w is not None and len(w) >= 30:
            c = w["close"].values; sma40c = float(c[-40:].mean()); ema10c = float(ema(list(c[-260:])))
            wk_vol_x, wk_close_pos = weekly_climax(t)
        vals = {**{k: r.get(k) for k in COLS if k in r.index}, "px": r.px_close, "ey_hist_med": r.get("ey_hist_med"),
                "fcfy_hist_med": r.get("fcfy_hist_med"), "non_op": rw.get("non_op"), "sma40c": sma40c, "ema10c": ema10c,
                "fcfy_ev": r.get("fcfy_ev"), "wk_vol_x": wk_vol_x, "wk_close_pos": wk_close_pos}
        for k in ("ebit", "cfo", "capex", "equity", "debt", "cash", "shares_adj"): vals[k] = rw.get(k)
        rows[t] = [rnd(vals.get(k)) for k in COLS]
        has_fund = nz(rw.get("shares_adj")) is not None and any(nz(r.get(k)) is not None for k in ("ey", "fcfy", "roe"))
        sp = spcur.get(t) or {}
        meta_t[t] = [SECTORS.index(r.sector) if r.sector in SECTORS else SECTORS.index("Other"), 1 if has_fund else 0,
                     1 if bool(M4.is_fin(pd.Series([r.get("sic")])).iloc[0]) else 0, 1 if t in spcur else 0, int(r.form4 or 0),
                     1 if r.univ else 0, sp.get("name") or names.get(t) or ""]
    # multi-class aliasing: other share classes of a shipped company -> its primary (most panel rows)
    nrows = p2.groupby("ticker").size()
    alias = {}
    for c, tks in by_cik.items():
        have = [t for t in tks if t in rows]
        if not have: continue
        prim = max(have, key=lambda t: nrows.get(t, 0))
        for t in tks:
            if t not in rows: alias[t] = prim
    M = {"sq": sq, "sqA": sqA, "uq": uq, "fq": fq, "smult": smult, "regime": rg["regime"], "mq": mq, "tsy": float(ST.tsy_at([now])[0])}
    # scores of the current universe from the shipped (rounded) values -> score quantiles
    def feats(t): return dict(zip(COLS, rows[t])) | {"form4": meta_t[t][4]}
    sc = {t: live_scores(feats(t), SECTORS[meta_t[t][0]], meta_t[t][2] == 1, M) for t in rows}
    univ = [t for t in rows if meta_t[t][5] == 1 and meta_t[t][1] == 1]
    # v4.2 quantiles from the shipped values of the current universe (build date)
    UF = pd.DataFrame({t: feats(t) for t in univ}).T; UF["sector"] = [SECTORS[meta_t[t][0]] for t in univ]
    UF["bm_pts"] = [fsum_js(bm_static(feats(t), M["tsy"]).values()) for t in univ]
    UF["l15"] = [l15_static(feats(t), mq) for t in univ]
    v42q = {"bm": quant(UF.bm_pts), "l15": quant(UF.l15), "beta_down": quant(UF.beta_down),
            "sec": {s_: {k: quant(g[k]) for k in ("ey_hist_med", "fcfy_ev", "mom_12_1")} for s_, g in UF.groupby("sector")}}
    M["v42q"] = dict(v42q, blend=None)
    parts = {t: v42_parts(feats(t), SECTORS[meta_t[t][0]], M) for t in rows if meta_t[t][1] == 1}
    v42q["blend"] = quant(pd.Series([parts[t]["blend"] for t in univ])); M["v42q"] = v42q
    for t, pp in parts.items(): sc[t]["V42"] = v42_score(pp, M)
    for t in rows:
        if "V42" not in sc[t]: sc[t]["V42"] = None
    pq = {m: [rnd(x, 12) for x in np.quantile([sc[t][m] for t in univ], PCT)] for m in ("A", "S_quant", "U", "D", "S_price", "V42")}
    cal = {}
    for h in HORIZONS:
        o = pd.read_parquet(CACHE / f"oos_v4_{h}.parquet")
        cal[h] = {m: decile_table(o, m, f"yh{h}") for m in ("A", "S_quant", "S_price")}
        cal[h]["V42"] = decile_table(pd.read_parquet(CACHE / f"oos_v42_{h}.parquet"), "V42", f"yh{h}")
    base_rate = {h: float((pd.read_parquet(CACHE / f"oos_v42_{h}.parquet")[f"yh{h}"] > 0).mean()) for h in HORIZONS}
    # finalists: top 30 by the live quant score among the current universe (fundamentals required)
    fin30 = sorted(univ, key=lambda t: (-sc[t][live], t))[:30]
    style_bt = {}
    try:
        ln = json.load(open(CACHE / "lean_test_results.json"))
        style_bt = {lab: {h: {"ic": ln[str(h)]["wide"][k]["ic"], "t": ln[str(h)]["wide"][k]["t"]} for h in HORIZONS} for lab, k in (("BM", "BM"), ("M15", "L15"))}
    except Exception: pass
    meta = {"built": dt.datetime.now(LA).strftime("%Y-%m-%d %H:%M %Z"), "price_asof": str(now.date()), "horizons": HORIZONS,
            "cols": COLS, "price_dep": PRICE_DEP, "sectors": SECTORS, "live": live, "passed": passed,
            "v4": {str(h): {lab: {m: {k: res4[h][lab][m][k] for k in ("ic", "t", "p10", "tmb")} for m in M4.MODELS} for lab in ("haircut_drag", "raw")} for h in HORIZONS},
            "v4_pass": res4["pass"], "turnover": res4["turnover"],
            "sleeves": {k: [[f, s] for f, s in v] for k, v in M4.SLEEVES.items()}, "sleeves_fin": {"S1": [[f, s] for f, s in M4.S1_FIN], "S5": [[f, s] for f, s in M4.S5_FIN]},
            "sprice": [[f, s] for f, s in M4.SPRICE], "fin_mask": M4.FIN_MASK, "pillars": {k: [[f, s] for f, s in v] for k, v in M2.PILLARS.items()},
            "regime_w": M4.REGIME_W, "weather": weather, "sq": sq, "sqA": sqA, "uq": uq, "fq": fq, "mq": mq, "smult": smult, "pq": pq, "cal": cal,
            "base_rate": base_rate, "tsy": M["tsy"], "v42q": v42q, "v42_pass": res42["pass"],
            "v42": {str(h): {lab: {m: {k: res42[h][lab][m][k] for k in ("ic", "t", "p10", "tmb")} for m in ("V42", "A")} for lab in ("primary", "raw")} for h in HORIZONS},
            "v42_turnover": {"hyst": res42["turnover_hyst"], "topdec": res42["turnover_topdec"]},
            "magic": {"name": "Magic 15", "sub": "lean: quality compounders + downside protection", "pillars": {k: [[a, b] for a, b in ST.MAGIC[k]] for k in ST.LEAN},
                      "labels": ST.MAGIC_LABEL, "left_out": ST.LEFT_OUT},
            "style_bt": style_bt,
            "spy_w": {"keys": [str((d - pd.Timedelta(days=d.weekday())).date()) for d in spy_w.index[-262:]], "a": [round(float(x), 4) for x in spy_w.values[-262:]]}}
    meta["alias"] = alias
    S = {"meta": meta, "rows": rows, "tmeta": meta_t, "finalists": fin30, "parity": {t: sc[t] for t in list(rows)[:400]}}
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(S, open(OUT / "shared.json", "w"), separators=(",", ":"))
    print("shared:", len(rows), "tickers;", "live model", live, "| regime", rg["regime"], "| breadth", round(breadth, 3))
    return S

# ---------------- per-page files ----------------
def page(cfg, S, dossiers):
    dan = bool(cfg.get("danelfin"))
    books = {label: read_book(path, dan) for label, path in cfg["books"].items()}
    mine = sorted({r["t"] for rows in books.values() for r in rows})
    today = pd.Timestamp.today().normalize()
    keys = S["meta"]["spy_w"]["keys"][-53:]
    w53 = {}
    for t in mine:
        w = weekly_close(t)
        if w is None: continue
        a = w["adj"]; k = [str((d - pd.Timedelta(days=d.weekday())).date()) for d in a.index]
        m = dict(zip(k, a.values)); w53[t] = [rnd(m.get(x), 7) for x in keys]
    own = set(mine) | set(S["finalists"])
    dz = {t: d for t, d in dossiers.items() if t in own}
    earn = {t: next_earnings(t, today) for t in mine}
    data = {"meta": dict(S["meta"], page={"slug": cfg["slug"], "title": cfg["title"], "h1": cfg.get("h1", cfg["title"]),
                                           "danelfin": dan, "show_sp500": bool(cfg.get("show_sp500", True))}, w53_keys=keys, proxy_url=proxy_url()),
            "rows": S["rows"], "tmeta": S["tmeta"], "finalists": S["finalists"], "books": books, "w53": w53, "earn": earn, "dossiers": dz}
    if not dan:
        for rows in data["books"].values():
            for r in rows:
                for k in ("ai", "fund", "tech", "sent", "lowrisk"): r.pop(k, None)
    f = OUT / f"page_{cfg['slug']}.json"
    json.dump(data, open(f, "w"), separators=(",", ":"))
    json.dump(S["parity"], open(OUT / "parity.json", "w"))
    print("page", cfg["slug"], "->", f.name, f"{f.stat().st_size/1e6:.2f} MB", "| books", list(books), "| dossiers", len(dz))

def main():
    args = sys.argv[1:]
    only = args[args.index("--page") + 1] if "--page" in args else None
    pages = [p for p in load_config() if only in (None, p["slug"])]
    if "--site-only" in args and (OUT / "shared.json").exists():
        S = json.load(open(OUT / "shared.json"))
    else:
        S = shared()
    import intel_dossiers as I
    pool = I.load_all()   # generated dossiers (30-day cache) with Gary's manual_overrides.json applied
    for p in pages: page(p, S, pool)
    want = set(S["finalists"])
    for p in load_config():
        for path in p["books"].values(): want |= {x["t"] for x in read_book(path, False)}
    if "--no-audit" not in args: append_audit(S, want, pool)

if __name__ == "__main__":
    main()
