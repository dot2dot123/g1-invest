"""G1 v4.3 free-cash-flow (owner-earnings) features, point-in-time (docs/PREREGISTRATION_V4_3_FCF.md).
Reads only local SEC companyfacts (first-filed values, usable LAG_DAYS after filing) and panel_v2 (mcap, dates).
Writes cache/fcf_feats.parquet keyed by (date, ticker). Free data only; no network."""
import json, multiprocessing as mp, sys
import numpy as np, pandas as pd
from common import *
from fundamentals import flow_quarters, ttm_table, inst_table, PIT, FLOW, INST
from features import STALE_DAYS

EXTRA = {
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense",
            "ifrs:AdjustmentsForSharebasedPayments", "ifrs:ExpenseFromSharebasedPaymentTransactions"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization",
           "Depreciation", "ifrs:AdjustmentsForDepreciationAndAmortisationExpense", "ifrs:DepreciationAndAmortisationExpense"],
}
FLOWS = {k: FLOW[k] for k in ("cfo", "capex", "ni", "rev")} | EXTRA
INSTS = {k: INST[k] for k in ("cash", "ltdebt", "stdebt")}
YR = np.timedelta64(365, "D")

def load(t):
    f = EDGAR / f"{t}.facts.json"
    if not f.exists(): return None
    facts = json.load(open(f))
    F = {}
    for k, names in FLOWS.items():
        q, a = flow_quarters(facts, names); F[k] = PIT(ttm_table(q, a))
    for k, names in INSTS.items():
        F[k] = PIT(inst_table(facts, names))
    return F

def feats_at(F, t, mcap):
    t = pd.Timestamp(t); out = {}
    e, cfo0 = F["cfo"].at(t)
    if e is None or (t - pd.Timestamp(e)).days > STALE_DAYS or np.isnan(cfo0) or not (mcap > 0): return out
    def near(k, kk):
        return F[k].near(e - kk * YR, t) if F[k].ok else np.nan
    def fcf(kk):
        c = cfo0 if kk == 0 else near("cfo", kk)
        if np.isnan(c): return np.nan
        x = near("capex", kk)
        return c - (0.0 if np.isnan(x) else x)
    fc = np.array([fcf(k) for k in range(6)]); ni = np.array([near("ni", k) for k in range(6)])
    rv = np.array([near("rev", k) for k in range(6)])
    sbc0 = near("sbc", 0); da0 = near("da", 0); da2 = near("da", 2); cx0 = near("capex", 0); cx2 = near("capex", 2)
    g = lambda k: F[k].at(t)[1]
    ld, sd, ca = g("ltdebt"), g("stdebt"), g("cash")
    debt = np.nansum([ld, sd]) if not (np.isnan(ld) and np.isnan(sd)) else 0.0
    ev = mcap + debt - (0.0 if np.isnan(ca) else ca)
    f0 = fc[0]
    out["fcf0"] = f0
    out["fcf_mc"] = f0 / mcap
    out["fcf_ev2"] = f0 / ev if ev > 0 else np.nan
    oe = f0 - (0.0 if np.isnan(sbc0) else max(sbc0, 0.0))
    out["oe_ev"] = oe / ev if ev > 0 else np.nan               # owner earnings (FCF - SBC) / EV
    out["fcf_oe"] = oe                                          # $ owner earnings (for live re-pricing)
    out["sbc_rev"] = sbc0 / rv[0] if rv[0] and rv[0] > 0 and not np.isnan(sbc0) else np.nan
    a3 = fc[:3]
    out["fcf_avg3_ev"] = np.mean(a3) / ev if ev > 0 and not np.isnan(a3).any() else np.nan
    out["fcf_avg3"] = float(np.mean(a3)) if not np.isnan(a3).any() else np.nan
    for n in (3, 5):
        fn = fc[n]
        if np.isnan(fn): out[f"fcf_g{n}"] = np.nan
        elif f0 > 0 and fn > 0: out[f"fcf_g{n}"] = float(np.clip((f0 / fn) ** (1 / n) - 1, -0.5, 1.0))
        elif f0 > 0: out[f"fcf_g{n}"] = 1.0                    # turned FCF-positive
        else: out[f"fcf_g{n}"] = -0.5                           # FCF-negative now
    s_f, s_n = np.nansum(fc[:3]), np.nansum(ni[:3])
    if np.isnan(fc[:3]).any() or np.isnan(ni[:3]).any(): out["conv3"] = np.nan
    elif s_n > 0: out["conv3"] = float(np.clip(s_f / s_n, -1.0, 1.5))
    else: out["conv3"] = 1.5 if s_f > 0 else -1.0
    m = np.where((rv > 0), fc / np.where(rv > 0, rv, np.nan), np.nan)
    out["fcfm0"] = m[0]
    mm = m[~np.isnan(m)]
    out["fcfm_std5"] = float(np.std(mm, ddof=1)) if len(mm) >= 3 else np.nan
    r0 = cx0 / da0 if (da0 and da0 > 0 and not np.isnan(cx0)) else np.nan
    r2 = cx2 / da2 if (da2 and da2 > 0 and not np.isnan(cx2)) else np.nan
    out["capex_da"] = r0
    # FCF flattered by under-investment: capex/D&A fell >30% vs 2y ago to below 1x maintenance proxy, and FCF rose
    out["capex_cut"] = float(bool(not np.isnan(r0) and not np.isnan(r2) and r0 < 0.7 * r2 and r0 < 1.0
                                  and not np.isnan(fc[2]) and f0 > fc[2]))
    return out

def work(args):
    t, rows = args
    try:
        F = load(t)
        if F is None: return []
        res = []
        for d, mc in rows:
            o = feats_at(F, d, mc)
            if o: o["date"] = d; o["ticker"] = t; res.append(o)
        return res
    except Exception as ex:
        print("ERR", t, ex, file=sys.stderr); return []

if __name__ == "__main__":
    P = pd.read_parquet(CACHE / "panel_v2.parquet", columns=["date", "ticker", "univ", "mcap"])
    P = P[P.univ & (P.date >= "2013-06-30")]
    jobs = [(t, list(zip(g.date, g.mcap.astype(float)))) for t, g in P.groupby("ticker")]
    print("tickers", len(jobs), "rows", len(P), flush=True)
    out = []
    with mp.Pool(int(os.environ.get("G1_PROCS", "5"))) as pool:
        for i, r in enumerate(pool.imap_unordered(work, jobs, chunksize=4)):
            out.extend(r)
            if i % 400 == 0: print(i, flush=True)
    D = pd.DataFrame(out)
    D.to_parquet(CACHE / "fcf_feats.parquet")
    print(D.shape, D.drop(columns=["date", "ticker"]).notna().mean().round(3).to_dict())
