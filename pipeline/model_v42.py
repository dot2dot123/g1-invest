"""G1 v4.2 pre-registered test (docs/PREREGISTRATION_V4_2.md). Parameter-free; nothing fitted."""
import json
import numpy as np, pandas as pd
from common import *
import style as ST
import model_v4 as M4

SEC = ["date", "sector"]

def v42_score(W):
    """W: one or more dates of universe rows with BM, L15, ey_hist_med, fcfy_ev, mom_12_1, beta_down."""
    g = W.groupby("date"); gs = W.groupby(SEC)
    p1 = g.BM.rank(pct=True).fillna(.5); p2 = g.L15.rank(pct=True).fillna(.5)
    p3 = (gs.ey_hist_med.rank(pct=True).fillna(.5) + gs.fcfy_ev.rank(pct=True).fillna(.5)) / 2
    p4 = (gs.mom_12_1.rank(pct=True).fillna(.5) + (1 - g.beta_down.rank(pct=True)).fillna(.5)) / 2
    blend = (p1 + p2 + p3 + p4) / 4
    V = blend.groupby(W.date).rank(pct=True)
    V = np.where(W.BM < 4.0, np.minimum(V, 0.65), V)
    return 100 * pd.Series(V, index=W.index)

def add_style(W):
    W = W.copy()
    W["BM"] = ST.bm_components(W, ST.tsy_at(W.date)).sum(axis=1).values
    W["L15"] = 10 * ST.magic_pillars(W)[ST.LEAN].mean(axis=1).values
    return W

def hyst_turnover(df, col):
    prev, tos = None, []
    for d, g in df.groupby("date"):
        r = g[col].rank(pct=True); tk = g.ticker.values
        H = set(tk[r > 0.85]) | (prev & set(tk[r > 0.65]) if prev is not None else set())
        if prev is not None: tos.append(len(H - prev) / max(1, len(H)))
        prev = H
    return float(np.mean(tos))

if __name__ == "__main__":
    P = M4.haircut_labels(ST.add_hist(pd.read_parquet(CACHE / "panel_v2.parquet")))
    W = P[P.univ & (P.date >= "2013-06-30")].copy().reset_index(drop=True)
    W["A"] = M4.a_score(W)
    W = add_style(W)
    W["V42"] = v42_score(W).values
    T = W[W.date >= "2014-01-01"]
    tau = {m: hyst_turnover(T, m) for m in ("V42", "A")}
    tdec = {m: M4.top_turnover(T, m) for m in ("V42", "A")}
    print("hysteresis turnover", tau, "| top-decile turnover", tdec, flush=True)
    res = {"turnover_hyst": tau, "turnover_topdec": tdec, "gated_share": float((T.BM < 4).mean())}
    for h in HORIZONS:
        r = {}
        for lab, ycol, dr in (("primary", f"yh{h}", True), ("raw", f"y{h}", False)):
            L = T[T[ycol].notna()].copy(); L["y"] = L[ycol]
            r[lab] = {m: M4.evaluate(L, m, h, 2 * M4.DRAG_BPS * tau[m] * h if dr else 0.0) for m in ("V42", "A")}
        res[h] = r
        for m in ("V42", "A"):
            a, b = r["primary"][m], r["raw"][m]
            print(h, f"{m:4s} IC {a['ic']:.3f} t {a['t']:.2f} TMB {a['tmb']:+.3f} p10 {a['p10']:+.3f} | raw IC {b['ic']:.3f} TMB {b['tmb']:+.3f}", flush=True)
    wins = sum(res[h]["primary"]["V42"]["ic"] > res[h]["primary"]["A"]["ic"] for h in HORIZONS)
    ok_t = tau["V42"] <= 1.2 * tau["A"]
    res["pass"] = {"ic_wins": int(wins), "turnover_ratio": tau["V42"] / tau["A"], "turnover_ok": bool(ok_t), "PASS": bool(wins >= 4 and ok_t)}
    print("PASS check", res["pass"], flush=True)
    json.dump(res, open(CACHE / "model_v42_results.json", "w"), indent=1, default=float)
    for h in HORIZONS:  # out-of-sample rows for the site's calibration bands
        T[T[f"yh{h}"].notna()][["date", "ticker", "sector", "V42", "A", f"y{h}", f"yh{h}"]].to_parquet(CACHE / f"oos_v42_{h}.parquet")
