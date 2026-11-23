"""G1 v4.3 long-horizon features (docs/PREREGISTRATION_V4_3_LT.md): per-ticker point-in-time leadership-quality and
raw inputs for peer-relative positioning. Local SEC companyfacts only (first-filed, LAG_DAYS after filing). No network.
Writes cache/lt_feats.parquet keyed by (date, ticker)."""
import json, multiprocessing as mp, sys
import numpy as np, pandas as pd
from common import *
from fundamentals import flow_quarters, ttm_table, inst_table, PIT, FLOW, INST
from features import STALE_DAYS
YR = np.timedelta64(365, "D")
FL = {k: FLOW[k] for k in ("rev", "gp", "ebit", "ni", "capex")}
IN = {k: INST[k] for k in ("assets", "equity", "cash", "ltdebt", "stdebt")}

def load(t):
    f = EDGAR / f"{t}.facts.json"
    if not f.exists(): return None
    facts = json.load(open(f)); F = {}
    for k, n in FL.items():
        q, a = flow_quarters(facts, n); F[k] = PIT(ttm_table(q, a))
    for k, n in IN.items(): F[k] = PIT(inst_table(facts, n))
    return F

def sd(x, mn=3):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return float(np.std(x, ddof=1)) if len(x) >= mn else np.nan

def feats_at(F, t):
    t = pd.Timestamp(t); o = {}
    e, r0 = F["rev"].at(t)
    if e is None or (t - pd.Timestamp(e)).days > STALE_DAYS or not (r0 > 0): return o
    nr = lambda k, kk: (F[k].near(e - kk * YR, t) if F[k].ok else np.nan)
    ni_ = lambda k, kk: (F[k].near(e - kk * YR, t, tol=45) if F[k].ok else np.nan)
    rv = np.array([r0] + [nr("rev", k) for k in range(1, 7)])
    gp = np.array([nr("gp", k) for k in range(6)]); eb = np.array([nr("ebit", k) for k in range(6)])
    ni = np.array([nr("ni", k) for k in range(6)]); cx = np.array([nr("capex", k) for k in range(4)])
    pos = np.where(rv > 0, rv, np.nan)
    o["rev0"], o["rev3"] = rv[0], rv[3]
    yoy = rv[:6] / pos[1:7] - 1                                   # yoy_k for k = 0..5
    o["rev_yoy_std"] = sd(yoy[:5])
    ns = 0; nn = 0
    for k in range(4):                                             # big miss vs trailing 2y trend
        if np.isnan(yoy[k]) or np.isnan(yoy[k + 1]) or np.isnan(yoy[k + 2]): continue
        nn += 1; ns += yoy[k] < (yoy[k + 1] + yoy[k + 2]) / 2 - 0.10
    o["neg_surp"] = ns / nn if nn else np.nan
    o["ni_var"] = sd((ni[:5] - ni[1:6]) / pos[:5])
    gm = gp / pos[:6]; om = eb / pos[:6]
    o["gm_tr3"] = gm[0] - gm[3]; o["gm_std5"] = sd(gm); o["om_tr3"] = om[0] - om[3]
    def ic(kk):
        g = lambda k: (F[k].near(e - kk * YR, t, tol=45) if F[k].ok else np.nan)
        eq, c, ld, s_ = g("equity"), g("cash"), g("ltdebt"), g("stdebt")
        if np.isnan(eq): return np.nan
        return eq + (0 if np.isnan(ld) else ld) + (0 if np.isnan(s_) else s_) - (0 if np.isnan(c) else c)
    i0, i3 = ic(0), ic(3)
    r_0 = eb[0] / i0 if i0 and i0 > 0 and not np.isnan(eb[0]) else np.nan
    r_3 = eb[3] / i3 if i3 and i3 > 0 and not np.isnan(eb[3]) else np.nan
    o["roic_tr3"] = float(np.clip(r_0 - r_3, -0.5, 0.5)) if not (np.isnan(r_0) or np.isnan(r_3)) else np.nan
    a0, a3 = ni_("assets", 0), ni_("assets", 3)
    o["asset_g3"] = float(np.clip((a0 / a3) ** (1 / 3) - 1, -0.3, 0.6)) if a0 > 0 and a3 > 0 else np.nan
    o["capex_g3"] = float(np.clip((cx[0] / cx[3]) ** (1 / 3) - 1, -0.5, 1.0)) if cx[0] > 0 and cx[3] > 0 else np.nan
    return o

def work(args):
    t, ds = args
    try:
        F = load(t)
        if F is None: return []
        res = []
        for d in ds:
            x = feats_at(F, d)
            if x: x["date"] = d; x["ticker"] = t; res.append(x)
        return res
    except Exception as ex:
        print("ERR", t, ex, file=sys.stderr); return []

if __name__ == "__main__":
    P = pd.read_parquet(CACHE / "panel_v2.parquet", columns=["date", "ticker", "univ"])
    P = P[P.univ & (P.date >= "2013-06-30")]
    jobs = [(t, list(g.date)) for t, g in P.groupby("ticker")]
    extra = [a for a in sys.argv[1:]]          # optional live date for build_site: python lt_features.py YYYY-MM-DD
    out = []
    with mp.Pool(int(os.environ.get("G1_PROCS", "6"))) as pool:
        for i, r in enumerate(pool.imap_unordered(work, jobs, chunksize=4)):
            out.extend(r)
            if i % 500 == 0: print(i, flush=True)
    D = pd.DataFrame(out); D.to_parquet(CACHE / "lt_feats.parquet")
    print(D.shape, D.drop(columns=["date", "ticker"]).notna().mean().round(3).to_dict())
