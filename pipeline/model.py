"""Walk-forward backtest + final per-horizon logistic models (JS-exportable)."""
import json, sys, warnings
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
from common import *
warnings.filterwarnings("ignore")

PRICE = ["mom_12_1", "mom_6_1", "mom_3", "rev_1m", "dd_52w", "trend40", "vol_1y", "beta_2y", "mom_36_12", "mdd_3y"]
SHORT_FUND = ["sue", "rev_accel", "om_trend", "rev_g1", "ey", "fcfy", "dil_1y"]
MID_FUND = SHORT_FUND + ["roic", "gm", "accruals", "ey_vs_sector", "ey_vs_hist"]
LONG_FUND = ["ey", "fcfy", "sy", "bm", "roe", "roic", "gm", "om", "om_stab", "om_trend", "rev_g1", "rev_g3", "rev_accel",
             "lev", "intcov", "dil_1y", "dil_3y", "accruals", "ey_vs_hist", "fcfy_vs_hist", "ey_vs_sector", "fcfy_vs_sector"]
FEATS = {
    ("full", 6): ["mom_12_1", "mom_6_1", "mom_3", "rev_1m", "dd_52w", "trend40", "vol_1y", "beta_2y"] + SHORT_FUND,
    ("full", 12): ["mom_12_1", "mom_6_1", "mom_3", "rev_1m", "dd_52w", "trend40", "vol_1y", "beta_2y", "mom_36_12"] + MID_FUND,
}
for h in (24, 36, 48, 60):
    FEATS[("full", h)] = ["mom_12_1", "vol_1y", "beta_2y", "mom_36_12", "mdd_3y", "dd_52w"] + LONG_FUND
for h in HORIZONS:
    FEATS[("price", h)] = PRICE
START = {"full": pd.Timestamp("2010-06-30"), "price": pd.Timestamp("2003-01-31")}
C = 0.5

def load_panel():
    p = pd.read_parquet(CACHE / "panel.parquet")
    p = p[p.px_close.notna()]
    return p

def rank_norm(df, cols, by="date"):
    """Per-date percentile rank among S&P members, centered to [-0.5, 0.5]; missing -> 0 (median)."""
    out = df[cols].groupby(df[by]).rank(pct=True) - 0.5
    return out.fillna(0.0)

def prep(p, kind, h):
    cols = FEATS[(kind, h)]
    m = p[(p.member) & (p.date >= START[kind])].copy()
    X = rank_norm(m, cols)
    m = m[["date", "ticker", f"y{h}"]].join(X)
    return m, cols

def fit(X, y):
    clf = LogisticRegression(C=C, max_iter=2000)
    clf.fit(X, y)
    return clf

def walk_forward(p, kind, h, first_test_year=None):
    m, cols = prep(p, kind, h)
    lab = m[m[f"y{h}"].notna()]
    years = sorted(lab.date.dt.year.unique())
    preds = []
    for Y in years:
        cut = pd.Timestamp(f"{Y}-01-01")
        tr = lab[lab.date + pd.DateOffset(months=h) < cut]   # purged: training labels fully realized before test year
        if tr.date.nunique() < 36: continue
        te = lab[lab.date.dt.year == Y]
        if te.empty: continue
        clf = fit(tr[cols].values, (tr[f"y{h}"] > 0).astype(int).values)
        q = te[["date", "ticker", f"y{h}"]].copy(); q["p"] = clf.predict_proba(te[cols].values)[:, 1]
        preds.append(q)
    if not preds: return None, None
    oos = pd.concat(preds).rename(columns={f"y{h}": "y"})
    return oos, metrics(oos, h)

def metrics(oos, h):
    y = (oos.y > 0).astype(int)
    out = {"n_obs": int(len(oos)), "n_dates": int(oos.date.nunique()),
           "test_start": str(oos.date.min().date()), "test_end": str(oos.date.max().date()),
           "independent_periods": round(oos.date.nunique() / h, 1),
           "base_rate": float(y.mean()), "auc": float(roc_auc_score(y, oos.p)),
           "hit_rate": float(((oos.p > 0.5).astype(int) == y).mean()),
           "brier": float(np.mean((oos.p - y) ** 2)), "brier_base": float(np.mean((y.mean() - y) ** 2))}
    # hit rate of the top half by predicted p (does a "likely winner" beat SPY?)
    ics = []; spreads = []; tops = []; aucs = []
    for d, g in oos.groupby("date"):
        if len(g) < 50: continue
        ics.append(spearmanr(g.p, g.y).statistic)
        r = g.p.rank(pct=True)
        top = g[r > 0.9].y.mean(); bot = g[r <= 0.1].y.mean()
        spreads.append(top - bot); tops.append(g[r > 0.5].y.gt(0).mean())
        yy = (g.y > 0).astype(int)
        if yy.nunique() == 2: aucs.append(roc_auc_score(yy, g.p))
    ics = np.array(ics); spreads = np.array(spreads)
    eff = max(1.0, len(ics) / h)
    out.update({"rank_ic": float(np.nanmean(ics)), "rank_ic_sd": float(np.nanstd(ics)),
                "rank_ic_t_overlap_adj": float(np.nanmean(ics) / (np.nanstd(ics) + 1e-12) * np.sqrt(eff)),
                "ic_pos_share": float(np.mean(ics > 0)),
                "mean_date_auc": float(np.mean(aucs)) if aucs else None,
                "top_half_hit": float(np.mean(tops)),
                "top_minus_bottom_decile": float(np.nanmean(spreads)),
                "top_minus_bottom_annualized": float(np.sign(np.nanmean(spreads)) * ((1 + abs(np.nanmean(spreads))) ** (12 / h) - 1)),
                "tmb_share_positive": float(np.mean(spreads > 0))})
    # calibration by decile of p
    oos = oos.copy(); oos["bin"] = pd.qcut(oos.p, 10, labels=False, duplicates="drop")
    cal = oos.groupby("bin").agg(p_mean=("p", "mean"), hit=("y", lambda s: float((s > 0).mean())),
                                 p10=("y", lambda s: float(s.quantile(.1))), p50=("y", "median"),
                                 p90=("y", lambda s: float(s.quantile(.9))), n=("y", "size"))
    out["calibration"] = cal.reset_index().round(4).to_dict("records")
    out["ece"] = float(np.average(np.abs(cal.p_mean - cal.hit), weights=cal.n))
    # yearly rank IC (for stability view)
    yr = oos.groupby(oos.date.dt.year).apply(lambda g: np.nanmean([spearmanr(x.p, x.y).statistic for _, x in g.groupby("date") if len(x) > 50]))
    out["rank_ic_by_year"] = {int(k): round(float(v), 4) for k, v in yr.items()}
    return out

def band_table(oos):
    """Bands = realized out-of-sample excess-return quantiles for stocks with similar predicted probability."""
    edges = list(np.quantile(oos.p, np.linspace(0, 1, 11)))
    oos = oos.copy(); oos["bin"] = np.clip(np.searchsorted(edges[1:-1], oos.p, side="right"), 0, 9)
    rows = []
    for b, g in oos.groupby("bin"):
        rows.append({"bin": int(b), "p10": float(g.y.quantile(.1)), "p50": float(g.y.median()), "p90": float(g.y.quantile(.9)),
                     "hit": float((g.y > 0).mean()), "n": int(len(g))})
    return {"edges": [float(e) for e in edges], "rows": rows}

def final_model(p, kind, h):
    m, cols = prep(p, kind, h)
    lab = m[m[f"y{h}"].notna()]
    clf = fit(lab[cols].values, (lab[f"y{h}"] > 0).astype(int).values)
    return {"features": cols, "coef": [float(c) for c in clf.coef_[0]], "intercept": float(clf.intercept_[0]),
            "train_start": str(lab.date.min().date()), "train_end": str(lab.date.max().date()), "n_train": int(len(lab))}

if __name__ == "__main__":
    hs = [int(x) for x in sys.argv[1].split(",")]
    p = load_panel()
    res_path = CACHE / "model_results.json"
    allres = json.load(open(res_path)) if res_path.exists() else {}
    for kind in ("full", "price"):
        for h in hs:
            oos, met = walk_forward(p, kind, h)
            if oos is None: print(kind, h, "no oos"); continue
            oos.to_parquet(CACHE / f"oos_{kind}_{h}.parquet")
            fm = final_model(p, kind, h)
            allres[f"{kind}_{h}"] = {"metrics": met, "bands": band_table(oos), "model": fm}
            show = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in met.items() if k not in ("calibration", "rank_ic_by_year")}
            print(kind, h, show, flush=True)
            print("   coef:", dict(zip(fm["features"], np.round(fm["coef"], 3))), flush=True)
    json.dump(allres, open(res_path, "w"), indent=1)
