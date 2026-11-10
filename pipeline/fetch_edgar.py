"""Download SEC EDGAR companyfacts (XBRL) + submissions (SIC) for tickers with a current CIK mapping."""
import sys, json, time, threading, concurrent.futures as cf
import requests
from common import *

lock = threading.Lock(); last = [0.0]
def throttle():
    with lock:
        wait = last[0] + 0.13 - time.time()
        if wait > 0: time.sleep(wait)
        last[0] = time.time()

def get(url):
    for a in range(4):
        throttle()
        r = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip"}, timeout=60)
        if r.status_code == 404: return None
        if r.status_code in (429, 503): time.sleep(10); continue
        r.raise_for_status(); return r.content
    return None

def cikmap():
    m = json.load(open(CACHE / "company_tickers.json"))
    return {v["ticker"].upper(): int(v["cik_str"]) for v in m.values()}

def fetch(t, cik):
    f1 = EDGAR / f"{t}.facts.json"; f2 = EDGAR / f"{t}.sub.json"
    st = []
    if not f1.exists():
        c = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        if c: f1.write_bytes(c); st.append("facts")
        else: st.append("nofacts")
    if not f2.exists():
        c = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        if c:
            j = json.loads(c)
            keep = {k: j.get(k) for k in ("cik", "name", "sic", "sicDescription", "tickers", "exchanges", "fiscalYearEnd", "category")}
            f2.write_text(json.dumps(keep))
    return t, st

if __name__ == "__main__":
    tickers = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    m = cikmap()
    todo = []; miss = []
    for t in tickers:
        k = t.upper().replace(".", "-")
        cik = m.get(k) or m.get(t.upper())
        (todo.append((t, cik)) if cik else miss.append(t))
    print("mapped", len(todo), "unmapped", len(miss), flush=True)
    json.dump({"unmapped": miss, "mapped": {t: c for t, c in todo}}, open(CACHE / "cik_map.json", "w"))
    with cf.ThreadPoolExecutor(4) as ex:
        n = 0
        for t, st in ex.map(lambda x: fetch(*x), todo):
            n += 1
            if n % 100 == 0: print(n, flush=True)
    print("done")
