"""G1 v4.3 FCF-pillar test (docs/PREREGISTRATION_V4_3_FCF.md). Parameter-free; nothing fitted.
Compares V42 with three FCF variants on the v4.2 panel/labels and writes cache/model_v43_results.json (+ oos_v43_*)."""
import json, sys
import numpy as np, pandas as pd
from common import *
import style as ST
import model_v4 as M4
import model_v42 as V
from features import load_prices

SEC = ["date", "sector"]
P5_COLS = ["oe_ev", "fcf_avg3_ev", "fcf_g3", "fcf_g5", "conv3", "fcfm0", "fcfm_std5", "capex_cut", "fcf0"]
VARIANTS = ["V42", "V43_eq", "V43_heavy", "V43_gate"]

def pillars(W):
    g = W.groupby("date"); gs = W.groupby(SEC)
    p1 = g.BM.rank(pct=True).fillna(.5); p2 = g.L15.rank(pct=True).fillna(.5)
    p3 = (gs.ey_hist_med.rank(pct=True).fillna(.5) + gs.fcfy_ev.rank(pct=True).fillna(.5)) / 2
    p4 = (gs.mom_12_1.rank(pct=True).fillna(.5) + (1 - g.beta_down.rank(pct=True)).fillna(.5)) / 2
    r = lambda c: gs[c].rank(pct=True).fillna(.5)
    conv = W.conv3.clip(upper=1.5); W = W.assign(_conv=conv)
    gs = W.groupby(SEC)
    p5 = (0.35 * (r("oe_ev") + r("fcf_avg3_ev")) / 2 + 0.20 * (r("fcf_g3") + r("fcf_g5")) / 2 + 0.15 * gs._conv.rank(pct=True).fillna(.5)
          + 0.15 * r("fcfm0") + 0.15 * (1 - r("fcfm_std5")) - 0.15 * W.capex_cut.fillna(0))
    fin = (W.sector == "Financials").values
    p5 = pd.Series(np.where(fin, 0.5, p5), index=W.index)
    return p1, p2, p3, p4, p5, fin

def finish(blend, W):
    v = blend.groupby(W.date).rank(pct=True)
    return pd.Series(np.where(W.BM < 4.0, np.minimum(v, 0.65), v), index=W.index)

def score_all(W):
    p1, p2, p3, p4, p5, fin = pillars(W)
    out = {"P5": p5}
    out["V42"] = finish((p1 + p2 + p3 + p4) / 4, W)
    out["V43_eq"] = finish((p1 + p2 + p3 + p4 + p5) / 5, W)
    out["V43_heavy"] = finish(0.35 * p5 + 0.1625 * (p1 + p2 + p3 + p4), W)
    q20 = p5.groupby(W.date).transform(lambda s: s.quantile(0.2))
    bad = (~fin) & ((W.fcf0 < 0).values | (p5 <= q20).values)
    out["V43_gate"] = pd.Series(np.where(bad, np.minimum(out["V42"], 0.35), out["V42"]), index=W.index)
    return {k: 100 * v if k != "P5" else v for k, v in out.items()}

def extras(L, col, drag):
    tops, hits, n = [], [], 0
    for d, g in L.groupby("date"):
        if len(g) < 30: continue
        r = g[col].rank(pct=True); top = g[r > 0.9].y - drag
        tops.append(top.mean()); hits.append((top > 0).mean())
    return {"top_mean": float(np.mean(tops)), "hit": float(np.mean(hits))}

def monthly_returns(T):
    dates = sorted(T.date.unique()); dates = [d for d in dates if pd.Timestamp(d).is_month_end]
    spy = load_prices("SPY")["adj"]; s = spy.asof(pd.DatetimeIndex(dates)).values
    spy_r = pd.Series(s[1:] / s[:-1] - 1, index=dates[:-1])
    R = {}
    for t in T.ticker.unique():
        d = load_prices(t)
        if d is None: continue
        a = d["adj"]; px = a.asof(pd.DatetimeIndex(dates)).values
        first = a.index[0]
        px = np.where(np.array(dates) < first, np.nan, px)
        R[t] = px[1:] / px[:-1] - 1          # if the stock stopped trading, asof holds its last price (0% after)
    R = pd.DataFrame(R, index=dates[:-1])
    return R, spy_r

def portfolio(T, col, R, spy_r, n=30, cost=0.001):
    prev, rets, tos = set(), [], []
    for d in R.index:
        g = T[T.date == d]
        top = list(g.nlargest(n, col).ticker)
        x = R.loc[d, [t for t in top if t in R.columns]].dropna()
        to = len(set(top) - prev) / n if prev else 1.0
        rets.append(x.mean() - 2 * cost * to); tos.append(to); prev = set(top)
    pr = pd.Series(rets, index=R.index)
    eq = (1 + pr).cumprod(); se = (1 + spy_r).cumprod()
    yrs = len(pr) / 12
    down = spy_r < 0
    return {"cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "spy_cagr": float(se.iloc[-1] ** (1 / yrs) - 1),
            "mdd": float((eq / eq.cummax() - 1).min()), "spy_mdd": float((se / se.cummax() - 1).min()),
            "down_capture": float(pr[down].mean() / spy_r[down].mean()), "up_capture": float(pr[~down].mean() / spy_r[~down].mean()),
            "month_hit": float((pr > spy_r).mean()), "turnover": float(np.mean(tos[1:])), "months": int(len(pr))}

if __name__ == "__main__":
    P = M4.haircut_labels(ST.add_hist(pd.read_parquet(CACHE / "panel_v2.parquet")))
    W = P[P.univ & (P.date >= "2013-06-30")].copy().reset_index(drop=True)
    W = V.add_style(W)
    Fx = pd.read_parquet(CACHE / "fcf_feats.parquet")
    W = W.merge(Fx[["date", "ticker"] + P5_COLS], on=["date", "ticker"], how="left")
    print("FCF coverage (non-fin univ rows):", W.loc[W.sector != "Financials", "oe_ev"].notna().mean().round(3), flush=True)
    for k, v in score_all(W).items(): W[k] = v.values
    T = W[W.date >= "2014-01-01"].copy()
    print("V42 mirror max diff", float(np.abs(T.V42.values - V.v42_score(T).values).max()), flush=True)
    tau = {m: V.hyst_turnover(T, m) for m in VARIANTS}
    print("hyst turnover", {k: round(v, 4) for k, v in tau.items()}, flush=True)
    res = {"turnover_hyst": tau}
    HS = [6, 12, 24, 36, 48, 60]
    for h in HS:
        L = T[T[f"yh{h}"].notna()].copy(); L["y"] = L[f"yh{h}"]
        r = {}
        for m in VARIANTS + ["P5"]:
            dr = 2 * M4.DRAG_BPS * tau.get(m, tau["V42"]) * h
            r[m] = M4.evaluate(L, m, h, dr) | extras(L, m, dr)
        res[h] = r
        for m in VARIANTS + ["P5"]:
            a = r[m]; print(h, f"{m:10s} IC {a['ic']:.3f} t {a['t']:.2f} top {a['top_mean']:+.3f} hit {a['hit']:.3f} TMB {a['tmb']:+.3f} p10 {a['p10']:+.3f}", flush=True)
    R, spy_r = monthly_returns(T)
    res["top30"] = {m: portfolio(T, m, R, spy_r) for m in VARIANTS}
    for m, v in res["top30"].items(): print("top30", m, {k: round(x, 3) for k, x in v.items()}, flush=True)
    # decision rule (docs/PREREGISTRATION_V4_3_FCF.md section 6)
    cand = ["V43_eq", "V43_heavy", "V43_gate"]
    best = max(cand, key=lambda m: np.mean([res[h][m]["ic"] for h in (12, 24, 36)]))
    b, a = res, "V42"
    c1 = all(b[h][best]["ic"] > b[h][a]["ic"] for h in (12, 24, 36))
    c2 = sum(b[h][best]["top_mean"] >= b[h][a]["top_mean"] for h in (12, 24, 36)) >= 2
    c3 = b[12][best]["t"] >= 2.0
    tp = res["top30"]
    c4 = tp[best]["mdd"] >= tp[a]["mdd"] - 0.03 and tp[best]["down_capture"] <= tp[a]["down_capture"] + 0.05
    res["decision"] = {"best": best, "c1_ic": bool(c1), "c2_top": bool(c2), "c3_t12": bool(c3), "c4_downside": bool(c4), "PASS": bool(c1 and c2 and c3 and c4)}
    print("DECISION", res["decision"], flush=True)
    json.dump(res, open(CACHE / "model_v43_results.json", "w"), indent=1, default=float)
    for h in [3] + HS:
        yc = f"yh{h}"
        if yc in T: T[T[yc].notna()][["date", "ticker", "sector"] + VARIANTS + [f"y{h}", yc]].to_parquet(CACHE / f"oos_v43_{h}.parquet")
