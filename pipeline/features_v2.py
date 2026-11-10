"""Wide (Russell-1000-like) point-in-time panel for G1 v2. Reuses v1 feature code."""
import json, sys, multiprocessing as mp
import numpy as np, pandas as pd
from common import *
from features import process, month_ends, sic_sector, load_prices

KEEP = ["mom_12_1", "mom_6_1", "mom_3", "rev_1m", "dd_52w", "trend40", "vol_1y", "beta_2y", "mom_36_12", "mdd_3y", "px_close",
        "y6", "y12", "y24", "y36", "y48", "y60", "ey", "fcfy", "sy", "bm", "roe", "roic", "gm", "om", "om_stab", "om_trend",
        "rev_g1", "rev_g3", "rev_accel", "sue", "lev", "intcov", "dil_1y", "dil_3y", "accruals", "gpa", "roa", "mcap",
        "ey_hist_med", "ey_vs_hist", "fcfy_hist_med", "fcfy_vs_hist"]

def work(args):
    t, ds = args
    try:
        _, rows, raw = process(t, ds)
    except Exception as e:
        return t, None, None
    if rows is None: return t, None, None
    for c in KEEP:
        if c not in rows: rows[c] = np.nan
    r = rows[KEEP].astype("float32")
    r["ticker"] = t
    return t, r, raw

if __name__ == "__main__":
    base = [l.strip() for l in open(CACHE / "universe_all.txt") if l.strip()]
    wide = [t.replace("-", ".") for t in json.load(open("/workspace/g1-bulk/wide_cik.json"))]
    tickers = sorted(set(base) | set(wide))
    tickers = [t for t in tickers if (PRICES / f"{t}.parquet").exists() and (EDGAR / f"{t}.facts.json").exists()]
    print("tickers with prices+facts", len(tickers), flush=True)
    dates = month_ends("2010-01-31")
    asof = load_prices("SPY").index[-1]
    if dates[-1] < asof: dates.append(asof)
    else: dates[-1] = asof
    ds = [str(x.date()) for x in dates]
    frames, raws = [], {}
    with mp.Pool(7) as pool:
        for i, (t, r, raw) in enumerate(pool.imap_unordered(work, [(t, ds) for t in tickers], chunksize=4)):
            if r is not None: frames.append(r)
            if raw is not None: raws[t] = raw
            if i % 500 == 0: print(i, flush=True)
    panel = pd.concat(frames).reset_index().rename(columns={"index": "date"})
    sec = {}
    for t in tickers:
        f = EDGAR / f"{t}.sub.json"
        sec[t] = sic_sector(json.load(open(f)).get("sic")) if f.exists() else "Other"
    panel["sector"] = panel["ticker"].map(sec)
    mem = membership(); md = mem["date"].values; sets = [set(x) for x in mem["tickers"]]
    j = np.searchsorted(md, panel["date"].values, side="right") - 1
    panel["sp"] = [jj >= 0 and tk in sets[jj] for jj, tk in zip(j, panel["ticker"].values)]
    # point-in-time universe: price >= $5, mcap known, top 1000 by mcap at each date
    ok = (panel.px_close >= 5) & panel.mcap.notna() & (panel.mcap > 0)
    panel["mrank"] = panel[ok].groupby("date").mcap.rank(ascending=False)
    panel["univ"] = ok & (panel.mrank <= 1000)
    panel.to_parquet(CACHE / "panel_v2.parquet")
    json.dump({k: {a: (None if (b is None or (isinstance(b, float) and np.isnan(b))) else float(b)) for a, b in v.items()} for k, v in raws.items()},
              open(CACHE / "latest_fundamentals_v2.json", "w"))
    print(panel.shape, panel.univ.sum(), panel[panel.univ].groupby("date").size().describe().to_dict())
