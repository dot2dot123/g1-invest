"""Score the current universe and write cleartext page data (gitignored) for the two dashboards."""
import json, math, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from common import *
import model as M

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
    tick = {}
    for t, f in feats_by.items():
        kind = "full" if has_fund[t] else "price"
        sc = {}
        for h in HORIZONS:
            sc[h] = calib(f"{kind}_{h}", logit_p(f"{kind}_{h}", f))
        raw = latest_raw.get(t) or {}
        tick[t] = {"kind": kind, "sector": cur.loc[t, "sector"], "px": nz(cur.loc[t, "px_close"]),
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
            "horizons": HORIZONS, "secmed": secmed, "missing_sp": missing_sp,
            "n_sp": len(sp), "universe_note": "Current S&P 500 per Wikipedia constituents table (fetched at build) plus every ticker in the five books."}
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
