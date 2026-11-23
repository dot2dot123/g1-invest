"""G1 v4.3 LT test (docs/PREREGISTRATION_V4_3_LT.md): V42 vs V43F (FCF-only) vs horizon-specific V43S / V43L.
Parameter-free. Writes cache/model_v43lt_results.json and cache/oos_v43_{h}.parquet (calibration rows for the site)."""
import json
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from common import *
import style as ST
import model_v4 as M4
import model_v42 as V
import model_v43 as F5

LT_COLS = ["rev0", "rev3", "rev_yoy_std", "neg_surp", "ni_var", "gm_tr3", "gm_std5", "om_tr3", "roic_tr3", "asset_g3", "capex_g3"]
P6W = [("share_ch", .25), ("rel_rev_g3", .15), ("rel_om", .15), ("rel_roic", .20), ("rel_capex_g3", .10), ("rel_fcfm", .15)]
P7W = [("roic_5y_med", .15, 1), ("roic_tr3", .10, 1), ("gm_tr3", .10, 1), ("gm_std5", .10, -1), ("om_stab", .10, 1),
       ("rev_yoy_std", .10, -1), ("ni_var", .10, -1), ("neg_surp", .10, -1), ("dil_3y", .05, -1), ("alloc", .10, 1)]
FIN_NA = ["rel_om", "rel_roic", "rel_capex_g3", "rel_fcfm", "roic_5y_med", "roic_tr3", "gm_tr3", "gm_std5", "alloc"]
HZ_SCORE = {3: "V43S", 6: "V43S", 12: "V43S", 24: "V43L", 36: "V43L", 48: "V43L", 60: "V43L"}

def peer_group(W):
    ind = (W.sic // 100).astype("Int64").astype(str)
    n = W.groupby(["date", ind]).ticker.transform("size")
    return pd.Series(np.where(n >= 6, "I" + ind, "S" + W.sector.astype(str)), index=W.index)

def lt_derive(W):
    """Peer-relative and leadership features (needs fcfm0, rev_g3, om, roic_5y_med, dil_3y, sic, sector, LT_COLS)."""
    W = W.copy(); W["peer"] = peer_group(W); fin = W.sector == "Financials"
    both = W.rev0.gt(0) & W.rev3.gt(0)
    tot0 = W.rev0.where(both).groupby([W.date, W.peer]).transform("sum"); tot3 = W.rev3.where(both).groupby([W.date, W.peer]).transform("sum")
    W["share_ch"] = np.log((W.rev0 / tot0) / (W.rev3 / tot3)).where(both).clip(-1.5, 1.5)
    for new, c in (("rel_rev_g3", "rev_g3"), ("rel_om", "om"), ("rel_roic", "roic_5y_med"), ("rel_capex_g3", "capex_g3"), ("rel_fcfm", "fcfm0")):
        x = W[c].where(~fin) if new in FIN_NA else W[c]
        W[new] = x - x.groupby([W.date, W.peer]).transform("median")
    W["alloc"] = (W.roic_5y_med - 0.08) * W.asset_g3.clip(-0.1, 0.3)
    for c in FIN_NA:
        if c in W: W.loc[fin, c] = np.nan
    return W

def lt_pillars(W):
    g = W.groupby("date"); gs = W.groupby(["date", "sector"])
    p6 = sum(w * g[c].rank(pct=True).fillna(.5) for c, w in P6W)
    p7 = sum(w * (gs[c].rank(pct=True).fillna(.5) if s > 0 else (1 - gs[c].rank(pct=True)).fillna(.5)) for c, w, s in P7W)
    psue = gs.sue.rank(pct=True).fillna(.5)
    return p6, p7, psue

def scores(W):
    p1, p2, p3, p4, p5, fin = F5.pillars(W); p6, p7, psue = lt_pillars(W)
    return {"V42": 100 * F5.finish((p1 + p2 + p3 + p4) / 4, W),
            "V43F": 100 * F5.finish((p1 + p2 + p3 + p4 + p5) / 5, W),
            "V43S": 100 * F5.finish(0.35 * p4 + 0.10 * psue + 0.1375 * (p1 + p2 + p3 + p5), W),
            "V43L": 100 * F5.finish(0.15 * p4 + (0.85 / 6) * (p1 + p2 + p3 + p5 + p6 + p7), W),
            "P6": p6, "P7": p7}

def calib_stats(L, col):
    o = L[["date", col, "y"]].dropna().copy(); o["r"] = o.groupby("date")[col].rank(pct=True)
    o["dec"] = np.clip(np.ceil(o.r * 10) - 1, 0, 9)
    hit = o.groupby("dec").y.apply(lambda s: float((s > 0).mean()))
    top = o[o.dec == 9].y
    return {"hit_by_decile": [round(x, 4) for x in hit.values], "top_hit": float(hit.iloc[-1]), "bot_hit": float(hit.iloc[0]),
            "mono": float(spearmanr(hit.index, hit.values).statistic), "top_p10": float(top.quantile(.1)),
            "top_p50": float(top.median()), "top_p90": float(top.quantile(.9))}

def load_W():
    P = M4.haircut_labels(ST.add_hist(pd.read_parquet(CACHE / "panel_v2.parquet")))
    W = P[P.univ & (P.date >= "2013-06-30")].copy().reset_index(drop=True)
    W = V.add_style(W)
    W = W.merge(pd.read_parquet(CACHE / "fcf_feats.parquet")[["date", "ticker"] + F5.P5_COLS], on=["date", "ticker"], how="left")
    W = W.merge(pd.read_parquet(CACHE / "lt_feats.parquet")[["date", "ticker"] + LT_COLS], on=["date", "ticker"], how="left")
    W = lt_derive(W)
    for k, v in scores(W).items(): W[k] = v.values
    return W

if __name__ == "__main__":
    W = load_W(); T = W[W.date >= "2014-01-01"].copy()
    o3 = pd.read_parquet(CACHE / "oos_v42_3.parquet")[["date", "ticker", "y3", "yh3"]]
    T = T.merge(o3, on=["date", "ticker"], how="left")
    print("coverage", {c: round(float(T[c].notna().mean()), 3) for c in ["share_ch", "rel_roic", "roic_tr3", "rev_yoy_std", "alloc"]}, flush=True)
    MS = ["V42", "V43F", "V43S", "V43L"]
    tau = {m: V.hyst_turnover(T, m) for m in MS}
    res = {"turnover_hyst": tau}
    for h in [3] + HORIZONS:
        yc = f"yh{h}"
        L = T[T[yc].notna()].copy(); L["y"] = L[yc]; r = {}
        for m in MS + ["P6", "P7"]:
            dr = 2 * M4.DRAG_BPS * tau.get(m, tau["V42"]) * h
            r[m] = M4.evaluate(L, m, h, dr) | F5.extras(L, m, dr) | calib_stats(L, m)
        res[h] = r
        for m in MS + ["P6", "P7"]:
            a = r[m]; print(h, f"{m:5s} IC {a['ic']:.3f} t {a['t']:.2f} hit top/bot {a['top_hit']:.3f}/{a['bot_hit']:.3f} mono {a['mono']:+.2f} top p10/50/90 {a['top_p10']:+.3f}/{a['top_p50']:+.3f}/{a['top_p90']:+.3f}", flush=True)
    R, spy_r = F5.monthly_returns(T)
    res["top30"] = {m: F5.portfolio(T, m, R, spy_r) for m in MS}
    for m, v in res["top30"].items(): print("top30", m, {k: round(x, 3) for k, x in v.items()}, flush=True)
    def passes(hs_model):
        tp = res["top30"]; head = hs_model if isinstance(hs_model, str) else hs_model[24]
        c1 = tp[head]["cagr"] >= tp["V42"]["cagr"]; c2 = tp[head]["mdd"] >= tp["V42"]["mdd"]
        m_of = (lambda h: hs_model) if isinstance(hs_model, str) else (lambda h: hs_model[h])
        gaps = {h: res[h][m_of(h)]["ic"] - res[h]["V42"]["ic"] for h in HORIZONS}
        c3 = all(g >= -0.003 for g in gaps.values())
        return {"cagr_ok": bool(c1), "mdd_ok": bool(c2), "ic_ok": bool(c3), "ic_gaps": gaps, "PASS": bool(c1 and c2 and c3)}
    res["decision"] = {"v43": passes(HZ_SCORE), "v43f": passes("V43F")}
    res["decision"]["deploy"] = "V43" if res["decision"]["v43"]["PASS"] else ("V43F" if res["decision"]["v43f"]["PASS"] else None)
    print("DECISION", json.dumps(res["decision"], default=float), flush=True)
    json.dump(res, open(CACHE / "model_v43lt_results.json", "w"), indent=1, default=float)
    for h in [3] + HORIZONS:
        yc = f"yh{h}"
        if yc in T and T[yc].notna().any():
            T[T[yc].notna()][["date", "ticker", "sector"] + MS + [f"y{h}", yc]].to_parquet(CACHE / f"oos_v43_{h}.parquet")
