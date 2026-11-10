"""Point-in-time fundamentals from SEC companyfacts. Uses FIRST-FILED value for each period
(no restatement look-ahead) and makes a value usable only LAG_DAYS after its filing date."""
import json
import numpy as np, pandas as pd
from common import *

LAG_DAYS = 2
FLOW = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet", "RevenuesNetOfInterestExpense",
            "ifrs:Revenue"],
    "gp": ["GrossProfit", "ifrs:GrossProfit"],
    "ebit": ["OperatingIncomeLoss", "ifrs:ProfitLossFromOperatingActivities"],
    "ni": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ifrs:ProfitLossAttributableToOwnersOfParent", "ifrs:ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            "ifrs:CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "ifrs:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "intexp": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense",
               "ifrs:FinanceCosts", "ifrs:InterestExpense"],
}
INST = {
    "assets": ["Assets", "ifrs:Assets"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "ifrs:EquityAttributableToOwnersOfParent", "ifrs:Equity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash", "ifrs:CashAndCashEquivalents"],
    "ltdebt": ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "ifrs:NoncurrentPortionOfNoncurrentBorrowings", "ifrs:Borrowings"],
    "stdebt": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "ifrs:CurrentBorrowings", "ifrs:CurrentPortionOfNoncurrentBorrowings"],
}

def _records(facts, name, unit="USD"):
    tax = "us-gaap"
    if name.startswith("ifrs:"): tax, name = "ifrs-full", name[5:]
    if name.startswith("dei:"): tax, name = "dei", name[4:]
    u = facts.get("facts", {}).get(tax, {}).get(name, {}).get("units", {}).get(unit)
    if not u: return None
    d = pd.DataFrame(u)
    if d.empty: return None
    d["end"] = pd.to_datetime(d["end"]); d["filed"] = pd.to_datetime(d["filed"])
    if "start" in d: d["start"] = pd.to_datetime(d["start"])
    return d

def _first_filed(d, keys):
    return d.sort_values("filed").drop_duplicates(keys, keep="first")

def flow_quarters(facts, names):
    """Quarterly (3-month) values: direct 3m facts + differences of same-start YTD facts + Q4 = FY - 9M.
    Merges candidate concepts: earlier concepts win per period end."""
    allq = []
    for pri, n in enumerate(names):
        d = _records(facts, n)
        if d is None or "start" not in d: continue
        d = d.dropna(subset=["start"])
        d = _first_filed(d, ["start", "end"])
        d["dur"] = (d["end"] - d["start"]).dt.days
        q = d[(d.dur >= 80) & (d.dur <= 100)][["end", "val", "filed"]].copy()
        rows = [q]
        ytd = d[(d.dur >= 80) & (d.dur <= 380)].sort_values(["start", "end"])
        for s, g in ytd.groupby("start"):
            g = g.sort_values("end").reset_index(drop=True)
            for i in range(1, len(g)):
                gap = (g.end[i] - g.end[i - 1]).days
                if 80 <= gap <= 100:
                    rows.append(pd.DataFrame({"end": [g.end[i]], "val": [g.val[i] - g.val[i - 1]],
                                              "filed": [max(g.filed[i], g.filed[i - 1])]}))
        q = pd.concat(rows)
        q["pri"] = pri
        allq.append(q)
        ann = d[(d.dur >= 350) & (d.dur <= 380)][["end", "val", "filed"]].copy()
        ann["pri"] = pri + 0.5
        ann["annual"] = True
        allq.append(ann)
    if not allq: return None, None
    a = pd.concat(allq)
    a["annual"] = a.get("annual", False)
    a["annual"] = a["annual"].fillna(False).astype(bool)
    qtr = a[~a.annual].sort_values(["pri", "filed"]).drop_duplicates("end", keep="first")
    # collapse ends within a few days (52/53-week calendars)
    qtr = qtr.sort_values("end")
    ann = a[a.annual].sort_values(["pri", "filed"]).drop_duplicates("end", keep="first").sort_values("end")
    return qtr[["end", "val", "filed"]].reset_index(drop=True), ann[["end", "val", "filed"]].reset_index(drop=True)

def ttm_table(qtr, ann):
    """TTM rows (end, val, avail). Sum of 4 consecutive quarters spanning ~1y; annual facts also count."""
    rows = []
    if qtr is not None and len(qtr) >= 4:
        e = qtr.end.values; v = qtr.val.values; f = qtr.filed.values
        for i in range(3, len(qtr)):
            span = (e[i] - e[i - 3]) / np.timedelta64(1, "D")
            if 255 <= span <= 290:
                rows.append((e[i], v[i - 3:i + 1].sum(), f[i - 3:i + 1].max()))
    if ann is not None:
        for r in ann.itertuples():
            rows.append((np.datetime64(r.end), r.val, np.datetime64(r.filed)))
    if not rows: return None
    t = pd.DataFrame(rows, columns=["end", "val", "filed"])
    t = t.sort_values("filed").drop_duplicates("end", keep="first").sort_values("end").reset_index(drop=True)
    t["avail"] = t["filed"] + pd.Timedelta(days=LAG_DAYS)
    return t

def inst_table(facts, names, unit="USD"):
    parts = []
    for pri, n in enumerate(names):
        d = _records(facts, n, unit)
        if d is None: continue
        d = _first_filed(d, ["end"])
        d["pri"] = pri
        parts.append(d[["end", "val", "filed", "pri"]])
    if not parts: return None
    d = pd.concat(parts).sort_values(["pri", "filed"]).drop_duplicates("end", keep="first").sort_values("end").reset_index(drop=True)
    d["avail"] = d["filed"] + pd.Timedelta(days=LAG_DAYS)
    return d[["end", "val", "filed", "avail"]]

def shares_table(facts):
    """Diluted weighted-average shares (covers all share classes) first; cover-page shares as fallback."""
    parts = []
    d = _records(facts, "WeightedAverageNumberOfDilutedSharesOutstanding", "shares")
    if d is not None and "start" in d:
        d = d.dropna(subset=["start"])
        d = _first_filed(d, ["start", "end"])
        d["dur"] = (d["end"] - d["start"]).dt.days
        d = d.sort_values(["dur", "filed"]).drop_duplicates("end", keep="first")
        d["pri"] = 0
        parts.append(d[["end", "val", "filed", "pri"]])
    for pri, n in enumerate(["dei:EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"], 1):
        e = _records(facts, n, "shares")
        if e is not None:
            e = _first_filed(e, ["end"]); e["pri"] = pri
            parts.append(e[["end", "val", "filed", "pri"]])
    # fallback: implied diluted shares = quarterly net income / quarterly diluted EPS (multi-class filers often omit counts)
    eps = _records(facts, "EarningsPerShareDiluted", "USD/shares")
    q, _ = flow_quarters(facts, FLOW["ni"])
    if eps is not None and q is not None and "start" in eps:
        eps = eps.dropna(subset=["start"])
        eps = _first_filed(eps, ["start", "end"])
        eps = eps[((eps.end - eps.start).dt.days.between(80, 100))]
        j = eps.merge(q, on="end", suffixes=("_e", "_n"))
        j = j[j.val_e.abs() > 0.05]
        if len(j):
            parts.append(pd.DataFrame({"end": j.end, "val": (j.val_n / j.val_e).abs(), "filed": j[["filed_e", "filed_n"]].max(axis=1), "pri": 3}))
    if not parts: return None
    d = pd.concat(parts)
    # prefer diluted series when it is reasonably current; otherwise fall back
    d = d.sort_values(["pri", "filed"]).drop_duplicates("end", keep="first").sort_values("end").reset_index(drop=True)
    for pr in (0, 1, 2):
        if (d.pri == pr).any():
            lastp = d[d.pri == pr].end.max()
            d = d[(d.pri <= pr) | (d.end > lastp + pd.Timedelta(days=200))]
    d["avail"] = d["filed"] + pd.Timedelta(days=LAG_DAYS)
    return d[["end", "val", "filed", "avail"]].reset_index(drop=True)

class PIT:
    """Point-in-time accessor: latest-period row whose avail <= t."""
    def __init__(self, tab):
        self.ok = tab is not None and len(tab) > 0
        if not self.ok: return
        tab = tab.sort_values("avail").reset_index(drop=True)
        self.avail = tab["avail"].values.astype("datetime64[ns]")
        ends = tab["end"].values.astype("datetime64[ns]")
        best = np.zeros(len(tab), dtype=int); b = 0
        for i in range(len(tab)):
            if ends[i] >= ends[b]: b = i
            best[i] = b
        self.best = best; self.ends = ends; self.vals = tab["val"].values.astype(float)
        o = np.argsort(ends); self.s_ends = ends[o]; self.s_vals = self.vals[o]; self.s_avail = self.avail[o]
    def at(self, t):
        if not self.ok: return None, np.nan
        i = np.searchsorted(self.avail, np.datetime64(t, "ns"), side="right") - 1
        if i < 0: return None, np.nan
        j = self.best[i]; return self.ends[j], self.vals[j]
    def near(self, end, t, tol=25):
        """value for period ending ~end, known by t"""
        if not self.ok or end is None: return np.nan
        i = np.searchsorted(self.s_ends, end)
        best = np.nan; bd = tol + 1
        for k in (i - 1, i):
            if 0 <= k < len(self.s_ends) and self.s_avail[k] <= np.datetime64(t, "ns"):
                dd = abs((self.s_ends[k] - end) / np.timedelta64(1, "D"))
                if dd < bd: bd = dd; best = self.s_vals[k]
        return best
    def quarters(self):
        return self

def load_ticker(t):
    f = EDGAR / f"{t}.facts.json"
    if not f.exists(): return None
    facts = json.load(open(f))
    out = {}
    for k, names in FLOW.items():
        q, a = flow_quarters(facts, names)
        out[k] = PIT(ttm_table(q, a))
        if k == "ni":
            qq = q.copy() if q is not None else None
            if qq is not None:
                qq["avail"] = qq["filed"] + pd.Timedelta(days=LAG_DAYS)
            out["ni_q"] = PIT(qq)
        if k == "ebit" or k == "rev":
            pass
    for k, names in INST.items():
        out[k] = PIT(inst_table(facts, names))
    sh = shares_table(facts)
    if sh is not None and t == "BRK.B":
        sh = sh.copy(); sh["val"] = sh["val"] * 1500.0  # cover-page shares are Class-A equivalents
    out["shares"] = PIT(sh)
    return out
