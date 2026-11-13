"""G1 v4 quant engine: five sleeves -> upside U / downside-safety D -> regime-weighted S_quant, price-only S_price,
Shumway haircut + turnover drag labels, and the pre-registered test vs v2 composite A.
Every definition is frozen in docs/PREREGISTRATION_V4.md. Scoring functions are cross-sectional per date and are
reused by build_site.py (whose JS mirror lives in web/app.js)."""
import json, sys, warnings
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
from common import *
from features import load_prices, weekly
import model_v2 as M2
warnings.filterwarnings("ignore")

S1 = [("roic_5y_med", 1), ("inc_roic_3y", 1), ("fcf_conv", 1), ("gpa", 1), ("accruals", -1), ("dil_3y", -1)]
S2 = [("fcfy_adj_ev", 1), ("ey_adj_ev", 1), ("gated_ey_vs_hist", 1)]
S3 = [("sue", 1), ("rev_accel", 1), ("om_trend", 1), ("inc_gm", 1), ("rule_of_40", 1), ("def_rev_g1", 1), ("rd_roi", 1), ("post_filing_drift", 1)]
S4 = [("mom_12_1", 1), ("dd_52w", 1), ("vcp_ratio", -1), ("up_down_vol_50d", 1)]
S5 = [("lev", -1), ("intcov", 1), ("beta_down", -1), ("cvar_5", 1), ("f_score", 1)]
S1_FIN = [("roe", 1), ("roa", 1), ("roe_stab", 1), ("dil_1y", -1)]
S5_FIN = [("eq_assets", 1), ("bm", 1), ("beta_down", -1), ("cvar_5", 1), ("f_score", 1)]
SPRICE = [("mom_12_1", 1), ("dd_52w", 1), ("vcp_ratio", -1), ("beta_down", -1), ("cvar_5", 1)]
FIN_MASK = ["ey", "ey_adj_ev", "gpa", "roic", "roic_5y_med", "inc_roic_3y", "lev", "intcov"]
SLEEVES = {"S1": S1, "S2": S2, "S3": S3, "S4": S4, "S5": S5}
SLEEVE_LABEL = {"S1": "Quality", "S2": "Value (adjusted EV)", "S3": "Growth & inflection", "S4": "Trend & coil", "S5": "Left-tail shield"}
REGIME_W = {"on": 0.65, "neutral": 0.50, "off": 0.30}
SEC_GROUP = ["date", "sector"]
DRAG_BPS = 0.0010

def is_fin(sic):
    s = pd.to_numeric(sic, errors="coerce")
    return ((s >= 6000) & (s <= 6799)).fillna(False)

def prep(df):
    d = df.copy()
    d["gated_ey_vs_hist"] = d["ey_vs_hist"] * (d["om_trend"] >= 0).astype(float)
    d["_fin"] = is_fin(d["sic"]) if "sic" in d else False
    for f in FIN_MASK:
        if f in d: d.loc[d["_fin"], f] = np.nan
    if "form4_cluster" not in d: d["form4_cluster"] = 0.0
    return d

def sector_mult(d):
    """Per (date, sector) multiplier 0.85..1.15 from the median 6m risk-adjusted momentum (>= 5 names)."""
    x = d.assign(_ram=d["mom_6_1"] / d["vol_1y"])
    g = x[x._ram.notna() & np.isfinite(x._ram)].groupby(SEC_GROUP)._ram.agg(["median", "size"]).reset_index()
    g = g[g["size"] >= 5]
    g["k"] = g.groupby("date")["median"].rank(method="average")
    g["n"] = g.groupby("date")["median"].transform("size")
    g["mult"] = np.where(g.n > 1, 0.85 + 0.30 * (g.k - 1) / (g.n - 1).clip(lower=1), 1.0)
    m = d[SEC_GROUP].merge(g[SEC_GROUP + ["mult"]], on=SEC_GROUP, how="left")["mult"].fillna(1.0)
    return m.values

def _signed(r, s): return (r if s > 0 else 1 - r).fillna(0.5)

def sleeves(df):
    d = prep(df)
    out = pd.DataFrame(index=d.index)
    Rs = d.groupby(SEC_GROUP)[sorted({f for f, _ in S1 + S2 + S3 + S4})].rank(pct=True)
    Ru = d.groupby(["date"])[sorted({f for f, _ in S4 + S5 + SPRICE})].rank(pct=True)
    Rf = d.groupby(["date", "_fin"])[sorted({f for f, _ in S1_FIN + S5_FIN})].rank(pct=True)
    mean = lambda parts: pd.concat(parts, axis=1).mean(axis=1)
    f4 = 0.05 * d["form4_cluster"].fillna(0.0)
    out["S1"] = mean([_signed(Rs[f], s) for f, s in S1])
    out["S2"] = mean([_signed(Rs[f], s) for f, s in S2])
    out["S3"] = mean([_signed(Rs[f], s) for f, s in S3])
    out["smult"] = sector_mult(d)
    out["S4"] = mean([0.5 * _signed(Ru[f], s) + 0.5 * _signed(Rs[f], s) for f, s in S4]) * out["smult"]
    out["S5"] = mean([_signed(Ru[f], s) for f, s in S5]) + f4
    fin = d["_fin"]
    out.loc[fin, "S1"] = mean([_signed(Rf[f], s) for f, s in S1_FIN])[fin]
    out.loc[fin, "S5"] = (mean([_signed(Rf[f], s) for f, s in S5_FIN]) + f4)[fin]
    out["U"] = 100 * (0.35 * out.S3 + 0.35 * out.S4 + 0.30 * (out.S1 + out.S2) / 2)
    out["D"] = 100 * (0.50 * out.S5 + 0.30 * out.S1 + 0.20 * out.S2)
    sp = mean([_signed(Ru[f], s) for f, s in SPRICE]) - 0.15 * d["sma40_below"].fillna(0.0)
    out["S_price"] = 100 * sp.clip(0, 1)
    return out

# ---- form 4 clusters ----
def ticker_cik():
    m = dict(json.load(open(CACHE / "cik_map.json"))["mapped"])
    try:
        for t, c in json.load(open("/workspace/g1-bulk/wide_cik.json")).items(): m.setdefault(t.replace("-", "."), int(c))
    except Exception: pass
    return {t: int(c) for t, c in m.items()}

def form4_cluster(df):
    """1 if >= 3 distinct owners filed Form 4 open-market purchases in the 90 days up to each row's date."""
    f = CACHE / "form4_buys.parquet"
    if not f.exists(): return np.zeros(len(df)), None
    b = pd.read_parquet(f); last = b.filing_date.max()
    cik = df["ticker"].map(ticker_cik())
    by = {c: (g.filing_date.values.astype("datetime64[ns]"), g.owner.values) for c, g in b.groupby("cik")}
    out = np.zeros(len(df))
    for i, (c, t) in enumerate(zip(cik.values, df["date"].values.astype("datetime64[ns]"))):
        if c != c or int(c) not in by: continue
        fd, ow = by[int(c)]
        m = (fd <= t) & (fd > t - np.timedelta64(90, "D"))
        if m.any() and len(set(ow[m])) >= 3: out[i] = 1.0
    return out, last

# ---- regime (point in time) ----
def load_macro():
    return pd.read_parquet(CACHE / "fred.parquet"), load_prices("SPY")

def classify(px, sma, hy):
    """Mirrors classify() in app.js. HY missing -> its clauses are dropped (pre-registered)."""
    hy_ok = hy is not None and not (isinstance(hy, float) and np.isnan(hy))
    if px < sma or (hy_ok and hy > 5.5): return "off"
    if px > sma and (not hy_ok or hy < 4.5): return "on"
    return "neutral"

def regime_at(t, fred, spy):
    t = pd.Timestamp(t)
    w = weekly(spy[spy.index <= t])["adj"]
    sma = float(w.iloc[-40:].mean()); px = float(w.iloc[-1])
    hy_s = fred["BAMLH0A0HYM2"].dropna(); hy_s = hy_s[hy_s.index <= t - pd.Timedelta(days=1)]
    hy = float(hy_s.iloc[-1]) if len(hy_s) else np.nan
    return {"regime": classify(px, sma, hy), "spy": px, "sma40": sma, "hy": hy}

def master(U, D, regime):
    w = REGIME_W[regime]; return w * U + (1 - w) * D

# ---- labels ----
def haircut_labels(P):
    P = P.sort_values(["ticker", "date"]).copy()
    last = pd.to_datetime(P["last_px_ord"].astype("float64"), unit="D")
    P["_last"] = last.values; data_end = last.max()
    lr = P[P.date <= P["_last"]].groupby("ticker").tail(1).set_index("ticker")
    bad = ((lr.dd_52w < -0.5) | (lr.roa < 0)).reindex(P.ticker).fillna(False).values.astype(bool)
    real = (P["_last"] < data_end - pd.Timedelta(days=10)).values
    for h in HORIZONS:
        hc = (P["_last"] < P.date + pd.DateOffset(months=h)).values & real & bad
        P[f"yh{h}"] = np.where(hc, 0.7 * (1 + P[f"y{h}"]) - 1, P[f"y{h}"]); P[f"hc{h}"] = hc
    return P

def top_turnover(df, col):
    prev, tos = None, []
    for d, g in df.groupby("date"):
        top = set(g.ticker[g[col].rank(pct=True) > 0.9])
        if prev: tos.append(len(top - prev) / max(1, len(top)))
        prev = top
    return float(np.mean(tos)) if tos else 0.0

def evaluate(df, col, h, drag=0.0):
    ics, tmb, p10 = [], [], []
    for d, g in df.groupby("date"):
        if len(g) < 30 or g[col].nunique() < 2: continue
        ics.append(spearmanr(g[col], g.y).statistic)
        r = g[col].rank(pct=True); top = g[r > 0.9].y - drag
        tmb.append(top.mean() - g[r <= 0.1].y.mean()); p10.append(top.quantile(0.1))
    ics, tmb, p10 = map(np.array, (ics, tmb, p10))
    tt = lambda x: float(np.nanmean(x) / np.nanstd(x, ddof=1) * np.sqrt(len(x) / max(1.0, h)))
    return {"dates": int(len(ics)), "ic": float(np.nanmean(ics)), "t": tt(ics), "tmb": float(np.nanmean(tmb)), "tmb_t": tt(tmb),
            "p10": float(np.nanmean(p10)), "auc": float(roc_auc_score((df.y > 0).astype(int), df[col])), "drag": drag}

def a_score(W):
    R = (W.groupby(SEC_GROUP)[M2.A_FEATS].rank(pct=True) - 0.5).fillna(0.0)
    return np.mean([np.mean([s * R[f].values for f, s in comps], axis=0) for comps in M2.PILLARS.values()], axis=0)

def build_scored(P=None):
    if P is None: P = pd.read_parquet(CACHE / "panel_v2.parquet")
    P = haircut_labels(P)
    breadth = P[P.univ & P.sma40_below.notna()].groupby("date").sma40_below.apply(lambda s: float((s == 0).mean()))
    W = P[P.univ & (P.date >= "2010-06-30")].copy().reset_index(drop=True)
    W["A"] = a_score(W)
    W["form4_cluster"], f4_last = form4_cluster(W)
    S = sleeves(W)
    for c in S: W[c] = S[c].values
    fred, spy = load_macro()
    reg = {d: regime_at(d, fred, spy) | {"breadth": float(breadth.get(d, np.nan))} for d in sorted(W.date.unique())}
    W["regime"] = W.date.map(lambda d: reg[d]["regime"])
    W["S_quant"] = [master(u, dd, r) for u, dd, r in zip(W.U, W.D, W.regime)]
    return W, reg, f4_last

MODELS = ["S_quant", "A", "U", "D", "S_price"]

if __name__ == "__main__":
    W, reg, f4_last = build_scored()
    T = W[W.date >= "2014-01-01"]
    rc = pd.Series({str(d.date()): v["regime"] for d, v in reg.items() if d >= pd.Timestamp("2014-01-01")}).value_counts().to_dict()
    print("regime months 2014+:", rc, "| form4 rows flagged:", int(T.form4_cluster.sum()), "last form4 filing", f4_last, flush=True)
    tau = {m: top_turnover(T, m) for m in MODELS}
    print("top-decile monthly one-way turnover:", {k: round(v, 3) for k, v in tau.items()}, flush=True)
    res = {"regime_counts": rc, "turnover": tau, "form4_rows": int(T.form4_cluster.sum())}
    for h in HORIZONS:
        r = {}
        for lab, ycol, use_drag in (("haircut_drag", f"yh{h}", True), ("raw", f"y{h}", False)):
            L = T[T[ycol].notna()].copy(); L["y"] = L[ycol]
            r[lab] = {m: evaluate(L, m, h, 2 * DRAG_BPS * tau[m] * h if use_drag else 0.0) for m in MODELS}
        r["haircut_rows"] = int(T[f"hc{h}"].sum()); res[h] = r
        print(h, "haircut rows", r["haircut_rows"], flush=True)
        for m in MODELS:
            a, b = r["haircut_drag"][m], r["raw"][m]
            print(f"  {m:8s} IC {a['ic']:.3f} t {a['t']:.2f} p10 {a['p10']:+.3f} TMB {a['tmb']:+.3f} | raw IC {b['ic']:.3f} t {b['t']:.2f} p10 {b['p10']:+.3f} TMB {b['tmb']:+.3f}", flush=True)
    H = lambda h, m, k: res[h]["haircut_drag"][m][k]
    a = sum(H(h, "S_quant", "ic") > H(h, "A", "ic") for h in HORIZONS)
    b = H(12, "S_quant", "t") > 2.5 and H(24, "S_quant", "t") > 2.5
    c = sum(H(h, "S_quant", "p10") > H(h, "A", "p10") for h in HORIZONS)
    res["pass"] = {"a_ic_wins": int(a), "b_t12_t24": bool(b), "c_p10_wins": int(c), "PASS": bool(a >= 4 and b and c >= 4)}
    print("PASS check", res["pass"], flush=True)
    for h in HORIZONS:
        T[T[f"yh{h}"].notna()][["date", "ticker", "sector", "sp", "A", "U", "D", "S_quant", "S_price", f"y{h}", f"yh{h}"]].to_parquet(CACHE / f"oos_v4_{h}.parquet")
    json.dump(res, open(CACHE / "model_v4_results.json", "w"), indent=1, default=str)
