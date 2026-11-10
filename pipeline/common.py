import os, json, time, pathlib
import pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
PRICES = CACHE / "prices"
EDGAR = CACHE / "edgar"
for p in (CACHE, PRICES, EDGAR):
    p.mkdir(parents=True, exist_ok=True)
SEC_UA = "G1-invest research airbot@mail.grokbot.com"
YH_UA = "Mozilla/5.0"
HOLDINGS_DIR = pathlib.Path(os.environ.get("G1_HOLDINGS_DIR", "/workspace/uploads/nov8"))
BOOKS = {"OTW": "OTW_holdings.csv", "OTW2": "OTW2_holdings.csv", "SWB": "SWB_holdings.csv",
         "Jette": "Jette_holdings.csv", "NEW": "NEW_holdings.csv"}
HORIZONS = [6, 12, 24, 36, 48, 60]

def yahoo_sym(t):
    return t.replace(".", "-")

def load_books():
    out = {}
    for k, f in BOOKS.items():
        d = pd.read_csv(HOLDINGS_DIR / f)
        out[k] = d
    return out

def membership():
    s = pd.read_csv(CACHE / "sp500_hist.csv")
    s["date"] = pd.to_datetime(s["date"])
    s["tickers"] = s["tickers"].str.split(",")
    return s
