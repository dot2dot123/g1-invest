"""Buffett & Munger and Magic 15 rule-based style scores (see docs/PREREGISTRATION_STYLE_SCORES.md)."""
import numpy as np, pandas as pd
from common import *

BM_RULES = ["durable_roe", "low_leverage", "stable_margins", "consistent_profits", "gross_margin", "share_count", "fcf_vs_treasury"]
BM_MAX = {"durable_roe": 2, "low_leverage": 1, "stable_margins": 1, "consistent_profits": 1, "gross_margin": 2, "share_count": 1, "fcf_vs_treasury": 2}
MAGIC = {  # pillar -> [(feature, sign)]
    "deep_value": [("ey", 1), ("fcfy", 1), ("bm", 1), ("ey_vs_hist", 1)],
    "downside": [("lev", -1), ("intcov", 1), ("mdd_3y", 1), ("vol_1y", -1)],
    "macro_trend": [("mom_12_1", 1), ("trend40", 1), ("dd_52w", 1)],
    "durable_growth": [("rev_g3", 1), ("gm", 1), ("rev_g1", 1), ("om_trend", 1)],
    "compounders": [("roic", 1), ("gpa", 1), ("om_stab", 1), ("dil_3y", -1)],
    "yield_credit": [("fcfy", 1), ("intcov", 1), ("lev", -1), ("accruals", -1)],
}
MAGIC_LABEL = {"deep_value": "Margin of safety / deep value (Klarman, Pabrai)", "downside": "Downside & credit cycle (Marks, Karsh)",
               "macro_trend": "Macro / trend (Druckenmiller)", "durable_growth": "Durable growth / moat (Thiel, Botha, Lin, Fenton, Cohler)",
               "compounders": "Quality compounders (Ackman, Combs, Weschler)", "yield_credit": "Yield / credit value (Black, Rowan)"}
MAGIC_FEATS = sorted({f for v in MAGIC.values() for f, _ in v})

def add_hist(p):
    p = p.sort_values(["ticker", "date"]).copy()
    g = p.groupby("ticker")
    roll = lambda c, fn: g[c].transform(lambda s: getattr(s.rolling(60, min_periods=24), fn)())
    p["roe_med5"] = roll("roe", "median"); p["roe_min5"] = roll("roe", "min"); p["roa_min5"] = roll("roa", "min")
    return p

def _pts(cond_full, cond_half, missing, mx):
    out = np.where(cond_full, mx, np.where(cond_half, mx / 2 if mx == 1 else 1, 0)).astype(float)
    return np.where(missing, mx / 2, out)

def bm_components(d, tsy):
    """d: DataFrame or dict-like with columns; tsy: 10y yield as decimal (scalar or array)."""
    c = {}
    med, mn = d["roe_med5"], d["roe_min5"]
    c["durable_roe"] = np.where(med.isna(), 1.0, np.where((med >= .15) & (mn >= .10), 2.0, np.where(med >= .12, 1.0, 0.0)))
    c["low_leverage"] = np.where(d["lev"].isna(), .5, (d["lev"] <= .30).astype(float))
    c["stable_margins"] = np.where(d["om_stab"].isna(), .5, (d["om_stab"] >= -.03).astype(float))
    c["consistent_profits"] = np.where(d["roa_min5"].isna(), .5, (d["roa_min5"] > 0).astype(float))
    c["gross_margin"] = np.where(d["gm"].isna(), 1.0, np.where(d["gm"] >= .40, 2.0, np.where(d["gm"] >= .25, 1.0, 0.0)))
    c["share_count"] = np.where(d["dil_3y"].isna(), .5, (d["dil_3y"] <= 0).astype(float))
    f = d["fcfy"]
    c["fcf_vs_treasury"] = np.where(f.isna(), 1.0, np.where(f >= tsy, 2.0, np.where(f >= .6 * tsy, 1.0, 0.0)))
    return pd.DataFrame(c, index=d.index)

def magic_pillars(d, by="date"):
    """Per-date percentile ranks within the given frame (missing -> 0.5)."""
    R = d.groupby(by)[MAGIC_FEATS].rank(pct=True)
    out = {}
    for k, comps in MAGIC.items():
        out[k] = np.mean([(R[f] if s > 0 else 1 - R[f] + 1 / d.groupby(by)[f].transform("count")).fillna(.5).clip(0, 1) for f, s in comps], axis=0)
    return pd.DataFrame(out, index=d.index)

def tsy_at(dates):
    t = pd.read_parquet(CACHE / "tnx.parquet")["tnx"] / 100
    return t.reindex(pd.DatetimeIndex(dates), method="ffill").values
