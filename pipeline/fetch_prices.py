"""Download daily price history (close, adjclose, splits) from Yahoo's chart API."""
import sys, json, time, concurrent.futures as cf
import requests, pandas as pd, numpy as np
from common import *

def fetch(t, force=False):
    out = PRICES / f"{t}.parquet"
    if out.exists() and not force:
        return t, "cached"
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym(t)}"
           f"?period1=946684800&period2={int(time.time())}&interval=1d&events=div%2Csplit&includeAdjustedClose=true")
    for attempt in range(4):
        try:
            r = requests.get(url, headers={"User-Agent": YH_UA}, timeout=30)
            if r.status_code == 404:
                return t, "404"
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1)); continue
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            ts = res.get("timestamp")
            if not ts:
                return t, "empty"
            q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            df = pd.DataFrame({"close": q["close"], "adj": adj if adj else q["close"], "vol": q.get("volume")},
                              index=pd.to_datetime(ts, unit="s").normalize())
            df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
            sp = res.get("events", {}).get("splits", {})
            splits = [(pd.to_datetime(v["date"], unit="s").normalize(), v["numerator"] / v["denominator"]) for v in sp.values()]
            df["split"] = 1.0
            for d, f in splits:
                if d in df.index:
                    df.loc[d, "split"] = f
            df.to_parquet(out)
            return t, "ok"
        except Exception as e:
            err = str(e); time.sleep(2)
    return t, "fail:" + err[:80]

if __name__ == "__main__":
    tickers = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    force = "--force" in sys.argv
    stats = {}
    with cf.ThreadPoolExecutor(6) as ex:
        for t, s in ex.map(lambda x: fetch(x, force), tickers):
            stats[s.split(":")[0]] = stats.get(s.split(":")[0], 0) + 1
            if s not in ("ok", "cached"):
                print(t, s, flush=True)
    print(stats)
