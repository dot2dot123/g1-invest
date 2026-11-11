"""Score the current universe and write cleartext page data (gitignored) for the two dashboards."""
import json, math, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from common import *
import model as M
import model_v2 as M2
import style as ST

PCT = np.linspace(0, 1, 101)
FUND_STATIC = ["roe", "roic", "gm", "om", "om_stab", "om_trend", "rev_g1", "rev_g3", "rev_accel", "sue", "lev", "intcov",
               "dil_1y", "dil_3y", "accruals"]
BOOK_LABEL = {"OTW": "OTW", "OTW2": "OTW #2", "SWB": "SWB", "Jette": "Jette", "NEW": "NEW"}

def qpct(x, q):
    """Percentile of x within shipped quantiles q (101 points). Mirrors qpct() in app.js exactly."""
    if x is None or (isinstance(x, float) and math.isnan(x)): return None
    n = len(q)
    if x < q[0]: return 0.0
    if x > q[-1]: return 1.0
    lo = int(np.searchsorted(q, x, side="left")); hi = int(np.searchsorted(q, x, side="right")) - 1
    if lo <= hi: return (lo + hi) / 2 / (n - 1)
    a, b = hi, lo
    return (a + (x - q[a]) / (q[b] - q[a])) / (n - 1)

def nz(v):
    if v is None: return None
    try:
        f = float(v)
    except Exception: return None
    return None if (math.isnan(f) or math.isinf(f)) else f

def decile_table(oos):
    o = oos.copy()
    o["r"] = o.groupby("date").p.rank(pct=True)
    o["dec"] = np.clip((o.r * 10).apply(math.ceil) - 1, 0, 9)
    rows = []
    for d, g in o.groupby("dec"):
        rows.append({"mid": (d + 0.5) / 10, "hit": float((g.y > 0).mean()), "p10": float(g.y.quantile(.1)),
                     "p50": float(g.y.median()), "p90": float(g.y.quantile(.9)), "n": int(len(g))})
    return rows

def verdict(m):
    ic, t, tmb = m["rank_ic"], m["rank_ic_t_overlap_adj"], m["tmb_share_positive"]
    if ic > 0.03 and t > 1.5: return "some edge"
    if ic > 0.02 and t > 0.8: return "weak, not significant"
    if ic < -0.02: return "negative (worse than random)"
    return "no edge"

def main():
    res = json.load(open(CACHE / "model_results.json"))
    p = pd.read_parquet(CACHE / "panel.parquet")
    now = p.date.max()
    cur = p[p.date == now].set_index("ticker")
    spcur = json.load(open(CACHE / "sp500_current.json"))
    latest_raw = json.load(open(CACHE / "latest_fundamentals.json"))
    books = load_books()
    sp = [t for t in spcur if t in cur.index]
    missing_sp = [t for t in spcur if t not in cur.index]
    mem = cur.loc[sp]
    # sector medians (current S&P, by SIC-derived sector) for relative-valuation recompute in browser
    secmed = {k: mem.groupby("sector")[k].median().dropna().to_dict() for k in ("ey", "fcfy")}
    models = {}
    for key, r in res.items():
        kind, h = key.split("_"); h = int(h)
        fm = r["model"]
        q = {f: [float(x) for x in np.nanquantile(mem[f].astype(float), PCT)] for f in fm["features"]}
        models[key] = {"kind": kind, "h": h, "features": fm["features"], "coef": fm["coef"], "intercept": fm["intercept"],
                       "q": q, "train": [fm["train_start"], fm["train_end"]], "n_train": fm["n_train"]}
    # score function (python mirror of app.js)
    def logit_p(key, feats):
        m = models[key]; z = m["intercept"]
        for f, c in zip(m["features"], m["coef"]):
            v = qpct(nz(feats.get(f)), m["q"][f]); z += c * ((v - 0.5) if v is not None else 0.0)
        return 1 / (1 + math.exp(-z))
    all_tickers = list(dict.fromkeys(sp + [t for d in books.values() for t in d.Ticker]))
    feats_by = {}
    for t in all_tickers:
        if t not in cur.index: continue
        row = cur.loc[t]
        f = {k: nz(row.get(k)) for k in M.PRICE + FUND_STATIC + ["ey", "fcfy", "sy", "bm", "ey_vs_hist", "fcfy_vs_hist", "ey_vs_sector", "fcfy_vs_sector"]}
        sec = row.get("sector")
        for k in ("ey", "fcfy"):  # same sector medians the browser uses on refresh
            med = secmed[k].get(sec)
            f[f"{k}_vs_sector"] = (f[k] - med) if (f[k] is not None and med is not None) else None
        feats_by[t] = f
    has_fund = {t: (latest_raw.get(t) is not None and nz(latest_raw[t].get("shares_adj")) is not None and
                    any(feats_by[t].get(k) is not None for k in ("ey", "fcfy", "roe"))) for t in feats_by}
    # score distribution quantiles among current S&P members -> percentile -> OOS decile calibration
    for key in models:
        ps = [logit_p(key, feats_by[t]) for t in sp if t in feats_by]
        models[key]["pq"] = [float(x) for x in np.quantile(ps, PCT)]
        oos = pd.read_parquet(CACHE / f"oos_{key}.parquet")
        if key.startswith("price_"):
            # calibrate price-only buckets on the same test window as the full model so probabilities are comparable
            fs = pd.Timestamp(res["full_" + key.split("_")[1]]["metrics"]["test_start"])
            oos = oos[oos.date >= fs]
        models[key]["cal"] = decile_table(oos)
        models[key]["cal_window"] = [str(oos.date.min().date()), str(oos.date.max().date())]
        met = res[key]["metrics"]
        models[key]["metrics"] = {k: met[k] for k in met if k not in ("calibration",)}
        models[key]["verdict"] = verdict(met)
    def calib(key, p):
        m = models[key]; s = qpct(p, m["pq"]); cal = m["cal"]
        mids = [c["mid"] for c in cal]
        out = {"p_raw": p, "pct": s}
        for k in ("hit", "p10", "p50", "p90"):
            out[k] = float(np.interp(s, mids, [c[k] for c in cal]))
        return out
    # ---- G1 v2: pre-registered composite (Model A), replaces the v1 full model for names with fundamentals ----
    res2 = {int(k): v for k, v in json.load(open(CACHE / "model_v2_results.json")).items()}
    p2 = pd.read_parquet(CACHE / "panel_v2.parquet")
    cur2 = p2[p2.date == p2.date.max()].set_index("ticker")
    U2 = cur2[cur2.univ]
    sq = {}
    for sec, g in U2.groupby("sector"):
        sq[sec] = {f: ([float(x) for x in np.nanquantile(g[f].astype(float), PCT)] if g[f].notna().sum() >= 5 else None) for f in M2.A_FEATS}
    pillars = {k: [[f, s_] for f, s_ in v] for k, v in M2.PILLARS.items()}
    def comp_score(f, sec):
        qs = sq.get(sec) or {}
        pv = []
        for comps in pillars.values():
            vals = []
            for name, sign in comps:
                q = qs.get(name); v = qpct(nz(f.get(name)), q) if q else None
                vals.append(sign * ((v - 0.5) if v is not None else 0.0))
            pv.append(sum(vals) / len(vals))
        return sum(pv) / len(pv)
    for t in feats_by:  # A inputs from the v2 panel (same PIT code), sector tag for the browser
        if t in cur2.index:
            for k in M2.A_FEATS: feats_by[t][k] = nz(cur2.loc[t].get(k))
            feats_by[t]["_sector"] = cur2.loc[t, "sector"]
        else:
            feats_by[t]["_sector"] = cur.loc[t, "sector"]
    a_now = [comp_score({k: nz(U2.loc[t].get(k)) for k in M2.A_FEATS}, U2.loc[t, "sector"]) for t in U2.index]
    pqA = [float(x) for x in np.quantile(a_now, PCT)]
    for h in HORIZONS:
        r2 = res2[h]; oos2 = pd.read_parquet(CACHE / f"oos_v2_{h}.parquet").rename(columns={"A": "p"})
        w, spm, v1m = r2["wide"]["A"], r2["sp500"]["A"], res[f"full_{h}"]["metrics"]
        met = {"test_start": r2["test_window"][0], "test_end": r2["test_window"][1], "independent_periods": round(w["dates"] / h, 1),
               "base_rate": w["base_rate"], "auc": w["auc"], "mean_date_auc": None, "rank_ic": w["rank_ic"],
               "rank_ic_t_overlap_adj": w["ic_t_ovl"], "top_minus_bottom_decile": w["tmb"], "tmb_share_positive": w["tmb_pos"], "ece": w["ece"]}
        models[f"full_{h}"] = {"type": "comp", "kind": "full", "h": h, "pillars": pillars, "pq": pqA, "cal": decile_table(oos2),
                               "cal_window": r2["test_window"], "metrics": met, "verdict": verdict(met),
                               "cmp": {"sp_A": spm, "sp_B": r2["sp500"]["B"], "wide_B": r2["wide"]["B"],
                                       "v1": {"auc": v1m["auc"], "rank_ic": v1m["rank_ic"], "t": v1m["rank_ic_t_overlap_adj"], "tmb": v1m["top_minus_bottom_decile"]}}}
    def comp_calib(h, f):
        m = models[f"full_{h}"]; a = comp_score(f, f.get("_sector")); s = qpct(a, m["pq"]); mids = [c["mid"] for c in m["cal"]]
        o = {"p_raw": a, "pct": s}
        for k in ("hit", "p10", "p50", "p90"): o[k] = float(np.interp(s, mids, [c[k] for c in m["cal"]]))
        return o
    # ---- style boxes: Buffett & Munger rules + Magic 15 pillars (display only; see docs/PREREGISTRATION_STYLE_SCORES.md) ----
    ph = ST.add_hist(p2[p2.date >= p2.date.max() - pd.DateOffset(months=62)])
    hist_now = ph[ph.date == ph.date.max()].set_index("ticker")[["roe_med5", "roe_min5", "roa_min5"]]
    tsy_now = float(ST.tsy_at([p2.date.max()])[0])
    mq = {f: [float(x) for x in np.nanquantile(U2[f].astype(float), PCT)] for f in ST.MAGIC_FEATS}
    def bm_static(t, f):
        row = pd.DataFrame([{**{k: f.get(k) for k in ("lev", "om_stab", "gm", "dil_3y", "fcfy")},
                             **({k: nz(hist_now.loc[t, k]) for k in hist_now.columns} if t in hist_now.index else {"roe_med5": None, "roe_min5": None, "roa_min5": None})}]).astype(float)
        c = ST.bm_components(row, tsy_now).iloc[0].to_dict()
        c.pop("fcf_vs_treasury"); return {k: float(v) for k, v in c.items()}, {k: nz(row.iloc[0][k]) for k in ("roe_med5", "roe_min5", "roa_min5")}
    def bm_total(st, fcfy):
        fv = 1.0 if fcfy is None else (2.0 if fcfy >= tsy_now else (1.0 if fcfy >= .6 * tsy_now else 0.0))
        return sum(st.values()) + fv, fv
    def magic(f):
        out = {}
        for k, comps in ST.MAGIC.items():
            vals = []
            for name, sign in comps:
                v = qpct(nz(f.get(name)), mq[name])
                vals.append(.5 if v is None else (v if sign > 0 else 1 - v))
            out[k] = sum(vals) / len(vals)
        return 10 * sum(out.values()) / len(out), out
    st_res = json.load(open(CACHE / "style_test_results.json"))
    style_bt = {sc: {h: {"wide": {k: st_res["basic"][str(h)]["wide"][sc][k] for k in ("ic", "t", "tmb", "auc")},
                         "sp": {k: st_res["basic"][str(h)]["sp500"][sc][k] for k in ("ic", "t")},
                         "partial_ic": st_res[sc][str(h)]["redundancy"]["partial_ic"], "partial_t": st_res[sc][str(h)]["redundancy"]["partial_t"],
                         "corr_A": st_res[sc][str(h)]["redundancy"]["corr_with_A"]} for h in HORIZONS} for sc in ("BM", "M15")}
    tick = {}
    for t, f in feats_by.items():
        kind = "full" if has_fund[t] else "price"
        sc = {}
        for h in HORIZONS:
            sc[h] = comp_calib(h, f) if kind == "full" else calib(f"{kind}_{h}", logit_p(f"{kind}_{h}", f))
        raw = latest_raw.get(t) or {}
        sty = None
        if kind == "full":
            bst, hv = bm_static(t, f); bmt, fv = bm_total(bst, f.get("fcfy")); mt, mpil = magic(f)
            sty = {"bm_st": bst, "bm": bmt, "bm_fcf": fv, "hist": hv, "m15": mt, "m15p": mpil}
        tick[t] = {"sty": sty, "kind": kind, "sector": cur.loc[t, "sector"], "px": nz(cur.loc[t, "px_close"]),
                   "f": f, "raw": {k: nz(raw.get(k)) for k in ("rev", "ebit", "cfo", "capex", "equity", "debt", "cash", "shares_adj")},
                   "hist": {"ey": nz(cur.loc[t].get("ey_hist_med")), "fcfy": nz(cur.loc[t].get("fcfy_hist_med"))},
                   "s": sc, "sp": t in spcur,
                   "name": (spcur.get(t, {}) or {}).get("name"), "gics": (spcur.get(t, {}) or {}).get("sector")}
    # book metadata (Danelfin AI score, NEW shares)
    bk = {}
    for b, d in books.items():
        rows = []
        for _, r in d.iterrows():
            t = r["Ticker"]
            if t in tick and not tick[t]["name"]: tick[t]["name"] = r.get("Company")
            rows.append({"t": t, "name": r.get("Company"), "ai": nz(r.get("AI Score")),
                         "shares": nz(r.get("Shares")) if b == "NEW" else None, "scored": t in tick})
        bk[b] = rows
    la = ZoneInfo("America/Los_Angeles")
    spy = pd.read_parquet(PRICES / "SPY.parquet")["adj"].resample("W-FRI").last().dropna().iloc[-262:]
    spy_keys = [str((d - pd.Timedelta(days=d.weekday())).date()) for d in spy.index]
    meta = {"spy_w": {"keys": spy_keys, "a": [round(float(x), 4) for x in spy.values]}, "built": dt.datetime.now(la).strftime("%Y-%m-%d %H:%M %Z"), "price_asof": str(now.date()),
            "horizons": HORIZONS, "secmed": secmed, "sq": sq, "mq": mq, "tsy": tsy_now,
            "magic": {"name": "Magic 15", "pillars": {k: [[a, b] for a, b in v] for k, v in ST.MAGIC.items()}, "labels": ST.MAGIC_LABEL},
            "style_bt": style_bt, "style_verdict": {"BM": "KEEP", "M15": "SIMPLIFY"}, "missing_sp": missing_sp,
            "n_sp": len(sp), "universe_note": "Composite ranks within SIC sector against the current top-1000 US-listed universe. Current S&P 500 per Wikipedia constituents table (fetched at build) plus every ticker in the five books."}
    full = {"meta": meta, "models": models, "tick": tick, "books": bk, "book_label": BOOK_LABEL}
    out = ROOT / "build" / "data"; out.mkdir(parents=True, exist_ok=True)
    json.dump(full, open(out / "main.json", "w"), separators=(",", ":"))
    keep = set(r["t"] for b in ("OTW", "OTW2") for r in bk[b])
    otw = dict(full); otw["tick"] = {t: v for t, v in tick.items() if t in keep}
    otw["books"] = {b: bk[b] for b in ("OTW", "OTW2")}
    json.dump(otw, open(out / "otw.json", "w"), separators=(",", ":"))
    # console summary for the report (local only)
    for b, rows in bk.items():
        for h in (12, 36):
            ranked = sorted([r["t"] for r in rows if r["t"] in tick], key=lambda t: -tick[t]["s"][h]["hit"])
            print(b, h, [(t, round(tick[t]["s"][h]["hit"], 3), tick[t]["kind"][0]) for t in ranked[:5]])
    print("missing", missing_sp, "price-only:", [t for t in tick if tick[t]["kind"] == "price"])
    for key in sorted(models): print(key, models[key]["verdict"], [round(c["hit"], 3) for c in models[key]["cal"]])

if __name__ == "__main__":
    main()
