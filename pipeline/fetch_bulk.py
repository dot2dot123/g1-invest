"""Wide-universe SEC data: download the SEC bulk companyfacts + submissions zips and extract one file per ticker.

Reads <bulk>/wide_cik.json (from fetch_universe.py) and cache/cik_map.json (from fetch_edgar.py).
Writes cache/edgar/{TICKER}.facts.json and {TICKER}.sub.json (subset of fields). Existing files are kept unless --force.
Usage: python fetch_bulk.py [--bulk DIR] [--skip-download] [--force]
"""
import argparse, json, pathlib, shutil, zipfile
import requests
from common import *

URLS = {"companyfacts.zip": "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
        "submissions.zip": "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"}
SUB_KEYS = ("cik", "name", "sic", "sicDescription", "tickers", "exchanges", "fiscalYearEnd", "category")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--bulk", default="/workspace/g1-bulk")
    ap.add_argument("--skip-download", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args(); bulk = pathlib.Path(a.bulk); bulk.mkdir(parents=True, exist_ok=True)
    if not a.skip_download:
        for fn, url in URLS.items():  # ~1.4 GB + ~1.6 GB
            with requests.get(url, headers={"User-Agent": SEC_UA}, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(bulk / (fn + ".part"), "wb") as f: shutil.copyfileobj(r.raw, f, length=1 << 22)
            (bulk / (fn + ".part")).rename(bulk / fn); print("downloaded", fn, flush=True)
    wide = json.load(open(bulk / "wide_cik.json"))
    cikmap = json.load(open(CACHE / "cik_map.json"))["mapped"] if (CACHE / "cik_map.json").exists() else {}
    want = {}
    for t, c in wide.items(): want.setdefault(int(c), t.replace("-", "."))
    for t, c in cikmap.items(): want.setdefault(int(c), t)
    z = zipfile.ZipFile(bulk / "companyfacts.zip"); names = set(z.namelist())
    s = zipfile.ZipFile(bulk / "submissions.zip"); snames = set(s.namelist())
    nf = ns = 0
    for cik, t in want.items():
        fn = f"CIK{cik:010d}.json"
        out = EDGAR / f"{t}.facts.json"
        if (a.force or not out.exists()) and fn in names: out.write_bytes(z.read(fn)); nf += 1
        out2 = EDGAR / f"{t}.sub.json"
        if (a.force or not out2.exists()) and fn in snames:
            j = json.loads(s.read(fn)); out2.write_text(json.dumps({k: j.get(k) for k in SUB_KEYS})); ns += 1
    print("facts written", nf, "submissions written", ns, "CIKs wanted", len(want))
