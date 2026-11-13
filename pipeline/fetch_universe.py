"""Build the universe files the pipeline reads (all free sources).

Writes:
  cache/sp500_hist.csv        historical S&P 500 membership (fja05680/sp500, "Updated" file; columns date,tickers)
  cache/sp500_current.json    current S&P 500 from Wikipedia {ticker: {name, sector, cik}}
  cache/company_tickers.json  SEC ticker -> CIK map (used by fetch_edgar.py)
  cache/universe_all.txt      S&P members since 2008 + current S&P + book tickers + SPY (v1 universe)
  cache/tnx.parquet           10-year Treasury yield (Yahoo ^TNX daily close, percent) for the Buffett & Munger FCF rule
  <bulk>/company_tickers_exchange.json, <bulk>/wide_cik.json, <bulk>/wide_need.txt  (wide v2 candidates)
Usage: python fetch_universe.py [--out DIR] [--bulk DIR]
"""
import argparse, io, json, pathlib, urllib.parse
from html.parser import HTMLParser
import pandas as pd, requests
from common import *

FJA = "https://raw.githubusercontent.com/fja05680/sp500/master/" + urllib.parse.quote("S&P 500 Historical Components & Changes (Updated).csv")
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SEC_T = "https://www.sec.gov/files/company_tickers.json"
SEC_TX = "https://www.sec.gov/files/company_tickers_exchange.json"

class Constituents(HTMLParser):
    """Minimal parser for Wikipedia's table id="constituents" (stdlib only, no lxml)."""
    def __init__(self):
        super().__init__(); self.on = False; self.depth = 0; self.rows = []; self.row = None; self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "constituents": self.on = True
        elif self.on and tag == "table": self.depth += 1
        if not self.on: return
        if tag == "tr": self.row = []
        elif tag in ("td", "th") and self.row is not None: self.cell = []
    def handle_endtag(self, tag):
        if not self.on: return
        if tag == "table":
            if self.depth: self.depth -= 1
            else: self.on = False
        elif tag in ("td", "th") and self.cell is not None: self.row.append("".join(self.cell).strip()); self.cell = None
        elif tag == "tr" and self.row: self.rows.append(self.row); self.row = None
    def handle_data(self, d):
        if self.on and self.cell is not None: self.cell.append(d)

def get(url, ua):
    r = requests.get(url, headers={"User-Agent": ua}, timeout=120); r.raise_for_status(); return r

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(CACHE)); ap.add_argument("--bulk", default="/workspace/g1-bulk")
    a = ap.parse_args(); out = pathlib.Path(a.out); bulk = pathlib.Path(a.bulk); out.mkdir(parents=True, exist_ok=True); bulk.mkdir(parents=True, exist_ok=True)
    (out / "sp500_hist.csv").write_bytes(get(FJA, YH_UA).content)
    html = get(WIKI, "G1-invest research (personal)").text; (out / "wiki_sp500.html").write_text(html)
    cp = Constituents(); cp.feed(html)
    t = pd.DataFrame(cp.rows[1:], columns=cp.rows[0])
    cur = {r["Symbol"]: {"name": r["Security"], "sector": r["GICS Sector"], "cik": str(r["CIK"]).zfill(10)} for _, r in t.iterrows()}
    json.dump(cur, open(out / "sp500_current.json", "w")); (out / "sp500_current.txt").write_text("\n".join(cur) + "\n")
    (out / "company_tickers.json").write_bytes(get(SEC_T, SEC_UA).content)
    s = pd.read_csv(out / "sp500_hist.csv"); s["date"] = pd.to_datetime(s["date"])
    hist = set(); [hist.update(x.split(",")) for x in s[s.date >= "2008-01-01"].tickers]
    books = {t for d in load_books().values() for t in d.Ticker}
    uni = sorted(hist | set(cur) | books | {"SPY"})
    (out / "universe_all.txt").write_text("\n".join(uni) + "\n")
    tx = get(SEC_TX, SEC_UA).json(); (bulk / "company_tickers_exchange.json").write_text(json.dumps(tx))
    wide = {}
    seen = set()
    for cik, name, tk, ex in tx["data"]:
        if ex in ("NYSE", "Nasdaq", "CBOE") and tk and cik not in seen:
            seen.add(cik); wide[tk] = cik
    json.dump(wide, open(bulk / "wide_cik.json", "w"))
    need = [t.replace("-", ".") for t in wide if not (PRICES / f"{t.replace('-', '.')}.parquet").exists()]
    (bulk / "wide_need.txt").write_text("\n".join(need) + "\n")
    import time
    r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?period1=946684800&period2={int(time.time())}&interval=1d", YH_UA).json()["chart"]["result"][0]
    tnx = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").normalize()).dropna()
    tnx[~tnx.index.duplicated()].to_frame("tnx").to_parquet(out / "tnx.parquet")
    print("hist rows", len(s), "current", len(cur), "universe_all", len(uni), "wide", len(wide), "wide_need", len(need))
