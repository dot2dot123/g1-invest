"""Test of the pre-registered lean Magic 15 (docs/PREREGISTRATION_LEAN_MAGIC15.md)."""
import json, numpy as np, pandas as pd
from scipy.stats import spearmanr
from common import *
import style as S, model_v2 as M2
from style_test import basic, per_date_ic, tstat

def main():
    p = S.add_hist(pd.read_parquet(CACHE / "panel_v2.parquet"))
    U = p[p.univ & (p.date >= "2010-06-30")].copy()
    U = U.merge(M2.load()[["date", "ticker", "A"]], on=["date", "ticker"], how="left")
    U["BM"] = S.bm_components(U, S.tsy_at(U.date)).sum(axis=1).values
    mp = S.magic_pillars(U)
    U["M15"] = 10 * mp.mean(axis=1).values
    U["L15"] = 10 * mp[["compounders", "downside"]].mean(axis=1).values
    out = {}
    for h in HORIZONS:
        L = U[U[f"y{h}"].notna() & (U.date >= "2014-01-01")].copy(); L["y"] = L[f"y{h}"]
        r = {"wide": {}, "sp500": {}}
        for uni, D in (("wide", L), ("sp500", L[L.sp])):
            for sc in ("A", "BM", "M15", "L15"): r[uni][sc] = basic(D, sc, h)
        d = L.copy(); d["ra"] = d.groupby("date").A.rank(pct=True)
        for sc in ("BM", "M15", "L15"):
            d["rs"] = d.groupby("date")[sc].rank(pct=True)
            corr = d.groupby("date").apply(lambda g: spearmanr(g.rs, g.ra).statistic)
            d["res"] = d.groupby("date", group_keys=False).apply(lambda g: g.rs - np.polyval(np.polyfit(g.ra, g.rs, 1), g.ra))
            pic = per_date_ic(d, "res"); d["stk"] = .5 * d.rs + .5 * d.ra
            diff = per_date_ic(d, "stk") - per_date_ic(d, "ra")
            r[f"red_{sc}"] = {"corr_A": float(corr.mean()), "partial_ic": float(pic.mean()), "partial_t": tstat(pic, h),
                              "stack_minus_A": float(diff.mean()), "stack_t": tstat(diff, h)}
        out[h] = r
        f = lambda x: f"AUC {x['auc']:.3f} IC {x['ic']:+.3f} t {x['t']:+.2f} TMB {x['tmb']:+.3f}"
        print(h)
        for uni in ("wide", "sp500"):
            for sc in ("A", "BM", "M15", "L15"): print("  ", uni, sc, f(r[uni][sc]))
        for sc in ("BM", "M15", "L15"): print("  ", sc, {k: round(v, 3) for k, v in r[f"red_{sc}"].items()})
        print("   L15 by year", r["wide"]["L15"]["by_year"], flush=True)
    json.dump(out, open(CACHE / "lean_test_results.json", "w"), indent=1, default=float)

if __name__ == "__main__":
    main()
