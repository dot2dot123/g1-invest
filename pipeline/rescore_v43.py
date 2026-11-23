"""Diagnostic: live re-score of shipped tickers under the v4.3 FCF candidates vs live V42 (build/data/shared.json).
Writes build/rescore_v43.json (gitignored). Prints only verdict/score changes for the requested tickers."""
import json, sys, multiprocessing as mp
import numpy as np, pandas as pd
from common import *
import build_site as B
import fcf_features as X

def fx(args):
    t, mc, asof = args
    try:
        F = X.load(t); return t, (X.feats_at(F, asof, mc) if F else {})
    except Exception: return t, {}

if __name__ == "__main__":
    S = json.load(open(ROOT / "build/data/shared.json")); meta = S["meta"]
    W = meta["weather"]; bear = W["spy"] < W["sma40"] and W["breadth"] < 0.35
    asof = meta["price_asof"]
    full = [t for t in S["rows"] if S["tmeta"][t][1] == 1]
    base = {}
    for t in full:
        q, sc, f = B.score_one(t, S)
        M = {k: meta[k] for k in ("mq", "tsy", "v42q")}
        pp = B.v42_parts(f, meta["sectors"][S["tmeta"][t][0]], M)
        base[t] = dict(q=q, sc=sc, f=f, parts=pp, sector=meta["sectors"][S["tmeta"][t][0]], univ=S["tmeta"][t][5] == 1)
    fcache = ROOT / "build/rescore_v43_fcf.json"
    if fcache.exists() and fcache.stat().st_mtime > (ROOT / "build/data/shared.json").stat().st_mtime:
        FF = json.load(open(fcache))
    else:
        with mp.Pool(5) as pool:
            FF = dict(pool.map(fx, [(t, float(base[t]["f"].get("mcap") or np.nan), asof) for t in full], chunksize=8))
        json.dump(FF, open(fcache, "w")); os.chmod(fcache, 0o600)
    D = pd.DataFrame({t: {**FF.get(t, {}), "sector": b["sector"], "univ": b["univ"], "BM": b["parts"]["bm"],
                          **{k: b["parts"][k] for k in ("P1", "P2", "P3", "P4")}} for t, b in base.items()}).T
    for c in D.columns:
        if c not in ("sector", "univ"): D[c] = pd.to_numeric(D[c], errors="coerce")
    U = D[D.univ.astype(bool)]
    def secrank(col, x, sec):  # percentile of x within the live universe's sector distribution (missing -> 0.5)
        v = U.loc[U.sector == sec, col].dropna().values
        if np.isnan(x) or len(v) < 5: return 0.5
        return float((np.sum(v < x) + 0.5 * np.sum(v == x)) / len(v)) if True else 0.5
    rows = {}
    for t, r in D.iterrows():
        if r.sector == "Financials": p5 = 0.5
        else:
            g = lambda c: secrank(c, r[c], r.sector)
            conv = min(r.conv3, 1.5) if not np.isnan(r.conv3) else np.nan
            vconv = U.loc[U.sector == r.sector, "conv3"].clip(upper=1.5).dropna().values
            rc = 0.5 if np.isnan(conv) or len(vconv) < 5 else float((np.sum(vconv < conv) + 0.5 * np.sum(vconv == conv)) / len(vconv))
            p5 = (0.35 * (g("oe_ev") + g("fcf_avg3_ev")) / 2 + 0.20 * (g("fcf_g3") + g("fcf_g5")) / 2 + 0.15 * rc
                  + 0.15 * g("fcfm0") + 0.15 * (1 - g("fcfm_std5")) - 0.15 * (0 if np.isnan(r.capex_cut) else r.capex_cut))
        rows[t] = p5
    D["P5"] = pd.Series(rows)
    D["b_eq"] = (D.P1 + D.P2 + D.P3 + D.P4 + D.P5) / 5
    D["b_hv"] = 0.35 * D.P5 + 0.1625 * (D.P1 + D.P2 + D.P3 + D.P4)
    Uu = D[D.univ.astype(bool)]
    pct = lambda col, x: float((np.sum(Uu[col].values < x) + 0.5 * np.sum(Uu[col].values == x)) / len(Uu))
    q20 = Uu.P5.quantile(0.2)
    out = {}
    for t, r in D.iterrows():
        b = base[t]; cap = (lambda v: min(v, 0.65) if r.BM < 4.0 else v)
        v42 = b["q"]
        eq = 100 * cap(pct("b_eq", r.b_eq)); hv = 100 * cap(pct("b_hv", r.b_hv))
        badf = r.sector != "Financials" and ((not np.isnan(r.get("fcf0", np.nan)) and r.fcf0 < 0) or r.P5 <= q20)
        gate = min(v42, 35.0) if badf else v42
        out[t] = {"V42": v42, "V43_eq": eq, "V43_heavy": hv, "V43_gate": gate, "P5": float(r.P5),
                  **{f"verdict_{k}": B.py_verdict(b["sc"], b["f"], s, bear) for k, s in (("V42", v42), ("V43_eq", eq), ("V43_heavy", hv), ("V43_gate", gate))}}
    (ROOT / "build").mkdir(exist_ok=True)
    json.dump({"asof": asof, "bear": bool(bear), "scores": out}, open(ROOT / "build/rescore_v43.json", "w"))
    os.chmod(ROOT / "build/rescore_v43.json", 0o600)
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    pxf = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--reprice=")), None)
    if pxf:   # re-score requested names at fresher weekly prices (universe distributions stay at the shipped build)
        PX = json.load(open(pxf)); bear = False
        for t in want:
            if t not in out or not (PX.get(t) or {}).get("ok"): continue
            p = PX[t]; b = base[t]; f0 = b["f"]; f = dict(f0)
            px = p["px"]; sh = f0.get("shares_adj")
            f.update(px=px, sma40c=p["sma40"], sma40_below=1 if p["below40"] else 0, dd_52w=p["dd52"], rev_1m=p["rev_1m"])
            if sh:
                mcap = px * sh; debt = f0.get("debt") or 0; cash = f0.get("cash") or 0; ev = mcap + debt - cash
                fcf = (f0["cfo"] - (f0.get("capex") or 0)) if f0.get("cfo") is not None else None
                f.update(mcap=mcap, fcfy=(fcf / mcap) if fcf is not None else None, fcfy_ev=(fcf / ev) if (fcf is not None and ev > 0) else None,
                         ey=(f0["ebit"] / ev) if (f0.get("ebit") is not None and ev > 0) else None)
            M = {k: meta[k] for k in ("sq", "sqA", "uq", "fq", "smult", "mq", "tsy", "v42q")} | {"regime": meta["weather"]["build_regime"]}
            sc = B.live_scores(f, b["sector"], S["tmeta"][t][2] == 1, M)
            pp = B.v42_parts(f, b["sector"], M); v42 = B.v42_score(pp, M)
            sc["kind"] = "full"; sc["Up"] = 100 * B.qpct(sc["U"], meta["pq"]["U"]); sc["Sp"] = 100 * B.qpct(sc["D"], meta["pq"]["D"])
            _, ffx = fx((t, float(f.get("mcap") or np.nan), asof)); r = dict(D.loc[t]); r.update(ffx)
            r.update({k: pp[k] for k in ("P1", "P2", "P3", "P4")}); r["BM"] = pp["bm"]
            if r["sector"] == "Financials": p5 = 0.5
            else:
                g = lambda c: secrank(c, float(r.get(c, np.nan)), r["sector"])
                cv = r.get("conv3", np.nan); vconv = U.loc[U.sector == r["sector"], "conv3"].clip(upper=1.5).dropna().values
                rc = 0.5 if np.isnan(cv) or len(vconv) < 5 else float((np.sum(vconv < min(cv, 1.5)) + 0.5 * np.sum(vconv == min(cv, 1.5))) / len(vconv))
                p5 = (0.35 * (g("oe_ev") + g("fcf_avg3_ev")) / 2 + 0.20 * (g("fcf_g3") + g("fcf_g5")) / 2 + 0.15 * rc
                      + 0.15 * g("fcfm0") + 0.15 * (1 - g("fcfm_std5")) - 0.15 * (0 if np.isnan(r.get("capex_cut", np.nan)) else r["capex_cut"]))
            cap = (lambda v: min(v, 0.65) if r["BM"] < 4.0 else v)
            beq = (r["P1"] + r["P2"] + r["P3"] + r["P4"] + p5) / 5; bhv = 0.35 * p5 + 0.1625 * (r["P1"] + r["P2"] + r["P3"] + r["P4"])
            eq = 100 * cap(pct("b_eq", beq)); hv = 100 * cap(pct("b_hv", bhv))
            badf = r["sector"] != "Financials" and ((ffx.get("fcf0", 1) < 0) or p5 <= q20); gate = min(v42, 35.0) if badf else v42
            out[t] = {"V42": v42, "V43_eq": eq, "V43_heavy": hv, "V43_gate": gate, "P5": float(p5), "px_asof": p.get("close_date"),
                      **{f"verdict_{k}": B.py_verdict(sc, f, s_, bear) for k, s_ in (("V42", v42), ("V43_eq", eq), ("V43_heavy", hv), ("V43_gate", gate))}}
        asof = asof + " (requested names repriced from " + pxf.split("/")[-1] + ")"
        json.dump({"asof": asof, "scores": out}, open(ROOT / "build/rescore_v43_repriced.json", "w")); os.chmod(ROOT / "build/rescore_v43_repriced.json", 0o600)
    print("price_asof", asof, "bear", bear)
    for t in want:
        if t not in out: print(t, "not scored (no fundamentals in shared bundle)"); continue
        o = out[t]
        ch = "" if o["verdict_V42"] == o["verdict_V43_eq"] else "  <-- CHANGE"
        print(f"{t:6s} V42 {o['V42']:5.1f} {o['verdict_V42']:26s} | V43_eq {o['V43_eq']:5.1f} {o['verdict_V43_eq']:26s} | heavy {o['V43_heavy']:5.1f} {o['verdict_V43_heavy'][:12]:12s} | gate {o['verdict_V43_gate'][:12]:12s} | P5 {o['P5']:.2f}{ch}")
