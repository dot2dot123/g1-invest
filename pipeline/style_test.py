"""Pressure test of B&M and Magic 15 (pre-registered in docs/PREREGISTRATION_STYLE_SCORES.md)."""
import json, numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from common import *
import style as S, model_v2 as M2

def tstat(x, h, py=12):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x) / max(1, h * py / 12))) if len(x) > 2 else np.nan

def per_date_ic(df, col):
    return df.groupby("date").apply(lambda g: spearmanr(g[col], g.y).statistic if g[col].nunique() > 1 else np.nan)

def basic(df, col, h):
    ic = per_date_ic(df, col)
    tmb = df.groupby("date").apply(lambda g: g[g[col].rank(pct=True) > .9].y.mean() - g[g[col].rank(pct=True) <= .1].y.mean())
    return {"auc": float(roc_auc_score((df.y > 0).astype(int), df[col])), "ic": float(ic.mean()), "t": tstat(ic, h),
            "tmb": float(tmb.mean()), "by_year": {int(k): round(float(v), 3) for k, v in ic.groupby(ic.index.year).mean().items()}}

def main():
    p = pd.read_parquet(CACHE / "panel_v2.parquet")
    p = S.add_hist(p)
    U = p[p.univ & (p.date >= "2010-06-30")].copy()
    # G1 v2 composite A (same as model_v2.load)
    A = M2.load()[["date", "ticker", "A"]]
    U = U.merge(A, on=["date", "ticker"], how="left")
    bmc = S.bm_components(U, S.tsy_at(U.date)); U["BM"] = bmc.sum(axis=1)
    for c in bmc: U[f"bm_{c}"] = bmc[c].values
    mp = S.magic_pillars(U)
    for c in mp: U[f"mg_{c}"] = mp[c].values
    U["M15"] = 10 * mp.mean(axis=1).values
    pil = {"BM": [f"bm_{c}" for c in S.BM_RULES], "M15": [f"mg_{c}" for c in S.MAGIC]}
    rng = np.random.default_rng(7); W = {k: rng.dirichlet(np.ones(len(v)), 200) for k, v in pil.items()}
    out = {}
    for h in HORIZONS:
        L = U[U[f"y{h}"].notna() & (U.date >= "2014-01-01")].copy(); L["y"] = L[f"y{h}"]
        r = {"window": [str(L.date.min().date()), str(L.date.max().date()), int(L.date.nunique())]}
        for uni, D in (("wide", L), ("sp500", L[L.sp])):
            r[uni] = {"A": basic(D, "A", h)}
            for sc in ("BM", "M15"):
                r[uni][sc] = basic(D, sc, h)
        # redundancy vs A (wide)
        for sc in ("BM", "M15"):
            d = L.copy()
            d["rs"] = d.groupby("date")[sc].rank(pct=True); d["ra"] = d.groupby("date").A.rank(pct=True)
            corr = d.groupby("date").apply(lambda g: spearmanr(g.rs, g.ra).statistic)
            def resid(g):
                b = np.polyfit(g.ra, g.rs, 1); return g.rs - (b[0] * g.ra + b[1])
            d["res"] = d.groupby("date", group_keys=False).apply(resid)
            pic = per_date_ic(d, "res")
            d["stk"] = .5 * d.rs + .5 * d.ra
            diff = per_date_ic(d, "stk") - per_date_ic(d, "ra")
            red = {"corr_with_A": float(corr.mean()), "partial_ic": float(pic.mean()), "partial_t": tstat(pic, h),
                   "stack_minus_A": float(diff.mean()), "stack_t": tstat(diff, h)}
            # ablation + single pillars + weight sensitivity (wide)
            cols = pil[sc]; base = r["wide"][sc]["ic"]
            abl, single = {}, {}
            for c in cols:
                d["tmp"] = d[[x for x in cols if x != c]].sum(axis=1) if sc == "BM" else d[[x for x in cols if x != c]].mean(axis=1)
                abl[c] = round(float(per_date_ic(d, "tmp").mean()) - base, 4)
                ic = per_date_ic(d, c); single[c] = {"ic": round(float(ic.mean()), 4), "t": round(tstat(ic, h), 2)}
            # normalize BM components to 0-1 for weighting
            Z = d[cols].values / (np.array([S.BM_MAX[c[3:]] for c in cols]) if sc == "BM" else 1)
            ics = []
            for w in W[sc]:
                d["tmp"] = Z @ w; ics.append(per_date_ic(d, "tmp").mean())
            pc = d.groupby("date")[cols].corr(method="spearman").groupby(level=1).mean().loc[cols, cols]
            out.setdefault(sc, {})[h] = {"redundancy": red, "ablation_dIC": abl, "single": single,
                                         "weights_ic_p5_p50_p95": [round(float(x), 4) for x in np.percentile(ics, [5, 50, 95])],
                                         "pillar_corr": pc.round(2).to_dict()}
        out.setdefault("basic", {})[h] = r
        f = lambda x: f"AUC {x['auc']:.3f} IC {x['ic']:+.3f} t {x['t']:+.2f} TMB {x['tmb']:+.3f}"
        print(h, r["window"])
        for uni in ("wide", "sp500"):
            for sc in ("A", "BM", "M15"): print("  ", uni, sc, f(r[uni][sc]))
        for sc in ("BM", "M15"):
            o = out[sc][h]; print("  ", sc, "red", {k: round(v, 3) for k, v in o["redundancy"].items()}, "w", o["weights_ic_p5_p50_p95"])
            print("     abl", o["ablation_dIC"]); print("     single", o["single"])
        print(flush=True)
    json.dump(out, open(CACHE / "style_test_results.json", "w"), indent=1, default=float)

if __name__ == "__main__":
    main()
