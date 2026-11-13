"""G1 v4.2 3-month pre-registered test (docs/PREREGISTRATION_V4_2_3M.md).

Adds a 3-month forward-excess label, evaluates the already-frozen V42 blend vs
composite A, and writes cache/model_v42_3m_results.json plus oos_v42_3.parquet.
Does not change HORIZONS or the live headline score. Run only after the
pre-registration doc has been committed.
"""
import json
import numpy as np
import pandas as pd
from common import *
import style as ST
import model_v4 as M4
import model_v42 as M42
from features import load_prices

H = 3


def add_y3(P, spy_adj):
    """3-month forward excess vs SPY on the monthly panel, same sit-in-SPY rule as features.fwd_excess."""
    P = P.sort_values(["ticker", "date"]).copy().reset_index(drop=True)
    last_spy = np.datetime64(pd.Timestamp(spy_adj.dropna().index[-1]).to_datetime64(), "ns")
    dts = pd.to_datetime(P.date).astype("datetime64[ns]")
    spy_on = pd.Series({d: float(spy_adj.asof(d)) for d in dts.unique()}, dtype="float64")
    sp = dts.map(spy_on).to_numpy(dtype="float64")
    px = P.px_close.to_numpy(dtype="float64")
    date3 = (dts + pd.DateOffset(months=H)).astype("datetime64[ns]").to_numpy()
    dates = dts.to_numpy()
    tickers = P.ticker.to_numpy()
    y = np.full(len(P), np.nan)
    change = np.r_[True, tickers[1:] != tickers[:-1], True]
    bounds = np.flatnonzero(change)
    for a, b in zip(bounds[:-1], bounds[1:]):
        gd, g3 = dates[a:b], date3[a:b]
        j = np.searchsorted(gd, g3, side="right") - 1
        p0, s0 = px[a:b], sp[a:b]
        p1, s1 = p0[np.clip(j, 0, b - a - 1)], s0[np.clip(j, 0, b - a - 1)]
        valid = (j >= 0) & (g3 <= last_spy) & np.isfinite(p0) & np.isfinite(s0) & (p0 > 0) & (s0 > 0)
        valid &= np.isfinite(p1) & np.isfinite(s1) & (p1 > 0) & (s1 > 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            y[a:b] = np.where(valid, (p1 / p0) / (s1 / s0) - 1.0, np.nan)
    P["y3"] = y
    return P


def haircut_h(P, h=H):
    """Same Shumway rule as model_v4.haircut_labels, for a single horizon."""
    P = P.sort_values(["ticker", "date"]).copy()
    last = pd.to_datetime(P["last_px_ord"].astype("float64"), unit="D")
    P["_last"] = last.values
    data_end = last.max()
    lr = P[P.date <= P["_last"]].groupby("ticker").tail(1).set_index("ticker")
    bad = ((lr.dd_52w < -0.5) | (lr.roa < 0)).reindex(P.ticker).fillna(False).values.astype(bool)
    real = (P["_last"] < data_end - pd.Timedelta(days=10)).values
    hc = (P["_last"] < P.date + pd.DateOffset(months=h)).values & real & bad
    P[f"yh{h}"] = np.where(hc, 0.7 * (1 + P[f"y{h}"]) - 1, P[f"y{h}"])
    P[f"hc{h}"] = hc
    return P


if __name__ == "__main__":
    print("computing 3m labels + V42 vs A (pre-registered in docs/PREREGISTRATION_V4_2_3M.md)", flush=True)
    spy = load_prices("SPY")
    if spy is None:
        raise SystemExit("SPY prices missing")
    spy_adj = spy["adj"].sort_index()
    P = ST.add_hist(pd.read_parquet(CACHE / "panel_v2.parquet"))
    # scores only need univ rows from mid-2013; labels need a little history but y3 uses px_close on the same frame
    W0 = P[P.univ & (P.date >= "2013-06-30")].copy()
    # y3 uses px_close; include enough last rows of delisted-looking names already in panel
    need = P[P.ticker.isin(W0.ticker.unique())].copy()
    need = add_y3(need, spy_adj)
    need = haircut_h(need, H)
    W = need[need.univ & (need.date >= "2013-06-30")].copy().reset_index(drop=True)
    W["A"] = M4.a_score(W)
    W = M42.add_style(W)
    W["V42"] = M42.v42_score(W).values
    T = W[W.date >= "2014-01-01"]
    tau = {m: M42.hyst_turnover(T, m) for m in ("V42", "A")}
    tdec = {m: M4.top_turnover(T, m) for m in ("V42", "A")}
    print("hysteresis turnover", tau, "| top-decile turnover", tdec, flush=True)
    r = {}
    for lab, ycol, dr in (("primary", "yh3", True), ("raw", "y3", False)):
        L = T[T[ycol].notna()].copy()
        L["y"] = L[ycol]
        r[lab] = {m: M4.evaluate(L, m, H, 2 * M4.DRAG_BPS * tau[m] * H if dr else 0.0) for m in ("V42", "A")}
    for m in ("V42", "A"):
        a, b = r["primary"][m], r["raw"][m]
        print(H, f"{m:4s} IC {a['ic']:.3f} t {a['t']:.2f} TMB {a['tmb']:+.3f} p10 {a['p10']:+.3f} | raw IC {b['ic']:.3f} TMB {b['tmb']:+.3f}", flush=True)
    ic_v, ic_a = r["primary"]["V42"]["ic"], r["primary"]["A"]["ic"]
    winner = "V42" if ic_v >= ic_a else "A"
    t_win = r["primary"][winner]["t"]
    unvalidated = bool(t_win < 2)
    res = {
        "horizon": H,
        "turnover_hyst": tau,
        "turnover_topdec": tdec,
        "primary": r["primary"],
        "raw": r["raw"],
        "winner": winner,
        "unvalidated": unvalidated,
        "t_winner": float(t_win),
        "ic_winner": float(r["primary"][winner]["ic"]),
        "ic_V42": float(ic_v),
        "ic_A": float(ic_a),
        "rule": "winner = V42 if IC(V42) >= IC(A) else A; unvalidated if t(winner) < 2; does not change live headline score",
    }
    print("winner", winner, "t", round(t_win, 2), "unvalidated", unvalidated, flush=True)
    json.dump(res, open(CACHE / "model_v42_3m_results.json", "w"), indent=1, default=float)
    T[T["yh3"].notna()][["date", "ticker", "sector", "V42", "A", "y3", "yh3"]].to_parquet(CACHE / "oos_v42_3.parquet")
    print("wrote", CACHE / "model_v42_3m_results.json", "and oos_v42_3.parquet", flush=True)
