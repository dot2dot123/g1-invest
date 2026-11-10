"""G1 v2 evaluation: pre-registered composite (A) and reworked learned model (B). See docs/PREREGISTRATION.md."""
import json, sys, warnings
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
from common import *
warnings.filterwarnings("ignore")

PRICE = ["mom_12_1", "mom_6_1", "mom_3", "rev_1m", "dd_52w", "trend40", "vol_1y", "beta_2y", "mom_36_12", "mdd_3y"]
LONG_FUND = ["ey", "fcfy", "sy", "bm", "roe", "roic", "gm", "om", "om_stab", "om_trend", "rev_g1", "rev_g3", "rev_accel",
             "lev", "intcov", "dil_1y", "dil_3y", "accruals", "ey_vs_hist", "fcfy_vs_hist"]
B_FEATS = LONG_FUND + PRICE + ["gpa", "roa"]
PILLARS = {"quality": [("gpa", 1), ("roa", 1), ("accruals", -1)],
           "value": [("fcfy", 1), ("ey", 1), ("ey_vs_hist", 1)],
           "dilution": [("dil_1y", -1)],
           "balance": [("lev", -1), ("intcov", 1)]}
A_FEATS = sorted({f for p in PILLARS.values() for f, _ in p})
ALPHA = 100.0

def load():
    p = pd.read_parquet(CACHE / "panel_v2.parquet")
    U = p[p.univ & (p.date >= "2010-06-30")].copy()
    feats = sorted(set(B_FEATS) | set(A_FEATS))
    R = U.groupby(["date", "sector"])[feats].rank(pct=True) - 0.5
    R = R.fillna(0.0)
    U[[f"r_{f}" for f in feats]] = R.values
    pil = []
    for name, comps in PILLARS.items():
        U[f"P_{name}"] = np.mean([s * U[f"r_{f}"] for f, s in comps], axis=0); pil.append(f"P_{name}")
    U["A"] = U[pil].mean(axis=1)
    return U

def ic_stats(df, col, h, per_year=12):
    ics, tmb = [], []
    for d, g in df.groupby("date"):
        if len(g) < 30 or g[col].nunique() < 2: continue
        ics.append(spearmanr(g[col], g.y).statistic)
        r = g[col].rank(pct=True); tmb.append(g[r > 0.9].y.mean() - g[r <= 0.1].y.mean())
    ics = np.array(ics); tmb = np.array(tmb)
    k = max(1.0, h * per_year / 12)
    tt = lambda x: float(np.nanmean(x) / np.nanstd(x, ddof=1) * np.sqrt(len(x) / k)) if len(x) > 2 else np.nan
    return {"dates": len(ics), "rank_ic": float(np.nanmean(ics)), "ic_t_ovl": tt(ics),
            "tmb": float(np.nanmean(tmb)), "tmb_t_ovl": tt(tmb), "tmb_pos": float(np.mean(tmb > 0))}

def metrics(df, col, h, per_year=12):
    yb = (df.y > 0).astype(int)
    m = {"obs": int(len(df)), "base_rate": float(yb.mean()), "auc": float(roc_auc_score(yb, df[col]))}
    m.update(ic_stats(df, col, h, per_year))
    if f"{col}_p" in df:
        q = df.dropna(subset=[f"{col}_p"]).copy()
        q["bin"] = pd.qcut(q[f"{col}_p"].rank(method="first"), 10, labels=False)
        cal = q.groupby("bin").agg(pm=(f"{col}_p", "mean"), hit=("y", lambda s: (s > 0).mean()), n=("y", "size"))
        m["ece"] = float(np.average((cal.pm - cal.hit).abs(), weights=cal.n))
    return m

def decile_p(train, test, col):
    """P(beat SPY) = training-period hit rate of the score's per-date decile."""
    tr = train.copy(); tr["dec"] = (tr.groupby("date")[col].rank(pct=True) * 10).clip(upper=9.999).astype(int)
    hit = tr.groupby("dec").apply(lambda g: (g.y > 0).mean())
    dec = (test.groupby("date")[col].rank(pct=True) * 10).clip(upper=9.999).astype(int)
    return dec.map(hit).values

def run(U, h):
    L = U[U[f"y{h}"].notna()].copy(); L["y"] = L[f"y{h}"]
    L["yr"] = L.groupby("date").y.rank(pct=True) - 0.5
    Xc = [f"r_{f}" for f in B_FEATS]
    out = []
    for Y in sorted(L.date.dt.year.unique()):
        if Y < 2014: continue
        cut = pd.Timestamp(f"{Y}-01-01")
        tr = L[L.date + pd.DateOffset(months=h) < cut]
        if tr.date.nunique() < 36: continue
        te = L[L.date.dt.year == Y].copy()
        if te.empty: continue
        mdl = Ridge(alpha=ALPHA).fit(tr[Xc].values, tr.yr.values)
        tr = tr.assign(B=mdl.predict(tr[Xc].values))
        te["B"] = mdl.predict(te[Xc].values)
        te["B_p"] = decile_p(tr, te, "B"); te["A_p"] = decile_p(tr, te, "A")
        out.append(te[["date", "ticker", "sector", "sp", "y", "A", "B", "A_p", "B_p"]])
    return pd.concat(out) if out else None, (Ridge(alpha=ALPHA).fit(L[Xc].values, L.yr.values), Xc)

if __name__ == "__main__":
    U = load()
    print("universe rows", len(U), "dates", U.date.nunique(), "avg names", round(U.groupby("date").size().mean()), flush=True)
    import glob, re
    dfn_dates = sorted(pd.Timestamp(re.search(r"date-(\d{4}-\d{2}-\d{2})\.json$", f).group(1))
                       for f in glob.glob("/workspace/g1-cache/danelfin/ranking__date-*.json") if re.search(r"date-\d{4}-\d{2}-\d{2}\.json$", f))
    print("danelfin quarter dates", len(dfn_dates), flush=True)
    dfn_months = {d.to_period("M") for d in dfn_dates}
    res = {}
    for h in HORIZONS:
        oos, (final, Xc) = run(U, h)
        if oos is None: continue
        oos.to_parquet(CACHE / f"oos_v2_{h}.parquet")
        r = {"test_window": [str(oos.date.min().date()), str(oos.date.max().date())]}
        for name, sub, py in (("wide", oos, 12), ("sp500", oos[oos.sp], 12),
                              ("sp500_dfn_quarters", oos[oos.sp & oos.date.dt.to_period("M").isin(dfn_months)], 4)):
            r[name] = {m: metrics(sub, m, h, py) for m in ("A", "B")}
        # sector-relative IC for information
        o2 = oos.copy(); o2["y"] = o2.y - o2.groupby(["date", "sector"]).y.transform("median")
        r["wide_sector_relative_ic"] = {m: ic_stats(o2, m, h)["rank_ic"] for m in ("A", "B")}
        r["B_coef"] = dict(zip([c[2:] for c in Xc], np.round(final.coef_, 4).tolist()))
        res[h] = r
        s = lambda x: f"AUC {x['auc']:.3f} IC {x['rank_ic']:.3f} t {x['ic_t_ovl']:.2f} TMB {x['tmb']:+.3f} ECE {x.get('ece', float('nan')):.3f}"
        print(h, r["test_window"], flush=True)
        for nm in ("wide", "sp500", "sp500_dfn_quarters"):
            print("  ", nm, "A:", s(r[nm]["A"]), "| B:", s(r[nm]["B"]), flush=True)
    json.dump(res, open(CACHE / "model_v2_results.json", "w"), indent=1)
