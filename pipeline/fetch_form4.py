"""SEC Insider Transactions Data Sets (free quarterly bulk Forms 3/4/5) -> cache/form4_buys.parquet with one row per
(issuer CIK, filing date, reporting owner) for Form 4 open-market purchases (non-derivative code "P").
Used for the v4 form4_cluster flag (docs/PREREGISTRATION_V4.md section 3)."""
import io, sys, time, zipfile, urllib.request, pathlib
import pandas as pd
from common import CACHE, SEC_UA

BULK = pathlib.Path(sys.argv[sys.argv.index("--bulk") + 1] if "--bulk" in sys.argv else "/workspace/g1-bulk") / "form4"
BASES = ["https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/",
         "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/"]

def quarters(start=2013, end=None):
    end = end or pd.Timestamp.today().year
    return [f"{y}q{q}" for y in range(start, end + 1) for q in range(1, 5)]

def download(q):
    f = BULK / f"{q}_form345.zip"
    if f.exists() and f.stat().st_size > 1000: return f
    for b in BASES:
        try:
            req = urllib.request.Request(b + f.name, headers={"User-Agent": SEC_UA})
            data = urllib.request.urlopen(req, timeout=120).read()
            f.write_bytes(data); time.sleep(0.3); return f
        except Exception:
            continue
    return None

def parse(f):
    z = zipfile.ZipFile(f)
    rd = lambda n, cols: pd.read_csv(z.open(n), sep="\t", usecols=cols, dtype=str, on_bad_lines="skip", quoting=3)
    sub = rd("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"])
    sub = sub[sub.DOCUMENT_TYPE.isin(["4", "4/A"])]
    tr = rd("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_CODE"])
    acc = set(tr[tr.TRANS_CODE == "P"].ACCESSION_NUMBER)
    own = rd("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK"])
    s = sub[sub.ACCESSION_NUMBER.isin(acc)].merge(own, on="ACCESSION_NUMBER")
    s["filing_date"] = pd.to_datetime(s.FILING_DATE, format="mixed", errors="coerce")
    return pd.DataFrame({"cik": pd.to_numeric(s.ISSUERCIK, errors="coerce"), "filing_date": s.filing_date,
                         "owner": pd.to_numeric(s.RPTOWNERCIK, errors="coerce")}).dropna()

if __name__ == "__main__":
    BULK.mkdir(parents=True, exist_ok=True)
    out, got = [], []
    for q in quarters():
        f = download(q)
        if f is None: continue
        try: out.append(parse(f)); got.append(q)
        except Exception as e: print("parse failed", q, type(e).__name__, flush=True)
    d = pd.concat(out).drop_duplicates()
    d["cik"] = d.cik.astype("int64"); d["owner"] = d.owner.astype("int64")
    d.to_parquet(CACHE / "form4_buys.parquet")
    print("quarters", got[0], "->", got[-1], len(got), "rows", len(d), "last filing", d.filing_date.max().date())
