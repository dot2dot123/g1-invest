#!/usr/bin/env python3
"""G1 live audit: score the weekly ledger (cache/live_audit.jsonl) against what prices did next.

Manual only (no cron). For every ledger row older than each horizon, computes the forward total return
(adjusted close, cached prices) minus SPY's over the same dates, then reports per horizon:
  - rank IC (Spearman) of quant_score and of dossier_score vs excess return, by week then averaged
  - hit rate (beat SPY) and mean excess return by verdict
Prints aggregates only (no holdings lists). Refresh prices first (scripts/rebuild.sh without --site-only) for current numbers.
Usage: .venv/bin/python scripts/track_signals.py [--horizons 4,13,26,52]
"""
import sys, json, argparse, pathlib
import pandas as pd, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pipeline"))
from common import CACHE
from features import load_prices

def adj_at(px, date, after=False):
    s = px["adj"]
    if after: s = s[s.index >= date]; return (s.index[0], s.iloc[0]) if len(s) else (None, None)
    s = s[s.index <= date]; return (s.index[-1], s.iloc[-1]) if len(s) else (None, None)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--horizons", default="4,13,26,52"); a = ap.parse_args()
    f = CACHE / "live_audit.jsonl"
    if not f.exists(): raise SystemExit("No ledger yet: run pipeline/build_site.py (it appends one snapshot per ISO week).")
    L = pd.DataFrame([json.loads(l) for l in open(f) if l.strip()])
    L["date"] = pd.to_datetime(L["date"])
    print(f"ledger: {len(L)} rows, {L.week.nunique()} week(s), {L.ticker.nunique()} tickers, {L.date.min().date()} .. {L.date.max().date()}")
    print("verdicts:", L.groupby("week").verdict.value_counts().unstack(fill_value=0).to_string())
    spy = load_prices("SPY")
    if spy is None: raise SystemExit("SPY prices missing in cache.")
    last = spy.index[-1]; cache = {}
    for hw in [int(x) for x in a.horizons.split(",")]:
        rows = []
        for r in L.itertuples():
            end = r.date + pd.Timedelta(weeks=hw)
            if end > last: continue
            px = cache.get(r.ticker) if r.ticker in cache else cache.setdefault(r.ticker, load_prices(r.ticker))
            if px is None: continue
            d0, p0 = adj_at(px, r.date); d1, p1 = adj_at(px, end)
            s0 = adj_at(spy, r.date)[1]; s1 = adj_at(spy, end)[1]
            if p0 is None or p1 is None or d1 <= d0: continue
            rows.append({"week": r.week, "q": r.quant_score, "dz": r.dossier_score, "verdict": r.verdict, "ex": p1 / p0 - s1 / s0})
        if not rows: print(f"\n{hw}w: no rows old enough yet (first results on or after {(L.date.min() + pd.Timedelta(weeks=hw)).date()})"); continue
        R = pd.DataFrame(rows)
        ic = R.groupby("week").apply(lambda g: g.q.corr(g.ex, method="spearman") if len(g) > 5 else np.nan).dropna()
        Rd = R.dropna(subset=["dz"]); icd = Rd.groupby("week").apply(lambda g: g.dz.corr(g.ex, method="spearman") if len(g) > 5 else np.nan).dropna()
        print(f"\n{hw}w: n={len(R)}  quant IC mean {ic.mean():.3f} over {len(ic)} wk  |  dossier IC mean {icd.mean() if len(icd) else float('nan'):.3f} (n={len(Rd)})")
        v = R.groupby("verdict").ex.agg(n="size", hit=lambda x: (x > 0).mean(), mean_excess="mean")
        print(v.round(3).to_string())

if __name__ == "__main__": main()
