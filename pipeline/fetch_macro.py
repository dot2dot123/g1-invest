"""Keyless FRED CSVs for the v3 Market Weather regime (docs/PREREGISTRATION_V3.md section 6).
BAMLH0A0HYM2 = ICE BofA US High Yield OAS (%; free history starts 2023-11-13); T10Y2Y = 10y-2y spread (%)."""
import io, time, urllib.request, urllib.parse
import pandas as pd
from common import CACHE

SERIES = ["BAMLH0A0HYM2", "T10Y2Y"]
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"

def get(url, tries=3):
    last = None
    for i in range(tries):
        for u in (url, "https://api.allorigins.win/raw?url=" + urllib.parse.quote(url, safe="")):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "curl/8"})
                return urllib.request.urlopen(req, timeout=60).read().decode()
            except Exception as e:
                last = e
        time.sleep(3)
    raise last

def fetch(s):
    d = pd.read_csv(io.StringIO(get(URL.format(s))))
    d.columns = ["date", s]
    d["date"] = pd.to_datetime(d["date"]); d[s] = pd.to_numeric(d[s], errors="coerce")
    return d.dropna().set_index("date")

if __name__ == "__main__":
    out = pd.concat([fetch(s) for s in SERIES], axis=1, sort=True)
    out.to_parquet(CACHE / "fred.parquet")
    for s in SERIES:
        x = out[s].dropna(); print(s, len(x), x.index[0].date(), x.index[-1].date())
