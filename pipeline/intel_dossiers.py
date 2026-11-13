"""Business-intelligence dossiers (G1 v4 overlay; rules frozen in docs/PREREGISTRATION_V4.md section 10).

Free public sources only: SEC XBRL facts already on disk, plus the SEC submissions API (recent filings, with links).
Each dossier is cached at cache/dossiers/{T}.json for 14 days. The scoring is rule-based and every claim carries a
source link. Optional analyst notes in cache/dossiers/notes/{T}.json may override a sub-score, but only if they cite
URLs. With thin evidence a sub-score is 0 and the dossier says so.

The overlay is NOT point-in-time and cannot be backtested, so f_strat is an unvalidated overlay. It feeds S_v4 only,
never S_quant, verdicts, sizes or stops.

Run for the configured books plus the top-30 finalists: `python intel_dossiers.py [--force]`.
Run for one ticker: `python analyze_ticker.py T`."""
import json, sys, time, datetime as dt, urllib.request
import numpy as np, pandas as pd
from common import *

DOSS = CACHE / "dossiers"; NOTES = DOSS / "notes"
TTL_DAYS = 14
RANGES = {"moat": (-2, 2), "stakes": (0, 3), "talent": (-1, 2), "pricing": (-2, 2), "variant": (-2, 2)}
LABELS = {"moat": "Moat vs disruption", "stakes": "Hidden stakes / SOTP", "talent": "Talent density & R&D",
          "pricing": "Pricing power & backlog", "variant": "Variant perception gap"}
FORM_NAMES = {"10-K": "annual report", "10-Q": "quarterly report", "8-K": "current report", "DEF 14A": "proxy statement",
              "S-1": "registration", "SC 13D": "activist stake", "SC 13G": "passive 5% stake", "4": "insider trade"}
ITEM_8K = {"1.01": "material agreement", "1.02": "agreement terminated", "2.01": "acquisition/disposition completed",
           "2.02": "results of operations", "2.05": "restructuring costs", "2.06": "impairment", "3.01": "listing notice",
           "4.02": "non-reliance on prior financials", "5.02": "officer/director change", "7.01": "Reg FD disclosure",
           "8.01": "other events", "9.01": "exhibits"}

def _nz(x):
    try: x = float(x)
    except Exception: return None
    return None if (np.isnan(x) or np.isinf(x)) else x

def facts_url(cik): return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
def filing_index(cik): return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik):010d}&type=&dateb=&owner=include&count=40"

def recent_filings(cik, n=12):
    """Recent SEC filings from the free submissions API (cached inside the dossier)."""
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": SEC_UA})
        js = json.loads(urllib.request.urlopen(req, timeout=30).read()); time.sleep(0.15)
    except Exception:
        return [], url
    r = js.get("filings", {}).get("recent", {})
    out = []
    for i in range(min(len(r.get("form", [])), 200)):
        f = r["form"][i]
        if f not in ("10-K", "10-Q", "8-K", "DEF 14A", "SC 13D", "SC 13D/A", "S-1"): continue
        acc = r["accessionNumber"][i].replace("-", "")
        link = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{r['primaryDocument'][i]}"
        out.append({"form": f, "date": r["filingDate"][i], "items": r.get("items", [""] * 999)[i], "url": link})
        if len(out) >= n: break
    return out, url

def score(row, ctx):
    """Rule-based sub-scores from point-in-time features at the build date. Returns scores, evidence and thin flags."""
    g = lambda k: _nz(row.get(k))
    s, ev, thin = {}, [], []
    cik = ctx.get("cik"); src = facts_url(cik) if cik else None
    # 1. moat vs disruption
    m = 0; used = 0
    if g("roic_5y_med") is not None:
        used += 1
        if g("roic_5y_med") >= 0.15: m += 1; ev.append(("moat", f"5-year median ROIC {g('roic_5y_med'):.0%} (≥15%)", src))
    gm, gm75, oms, oms50 = g("gm"), ctx.get("gm75"), g("om_stab"), ctx.get("oms50")
    if gm is not None and gm75 is not None and oms is not None and oms50 is not None:
        used += 1
        if gm >= gm75 and oms >= oms50: m += 1; ev.append(("moat", f"Gross margin {gm:.0%} in its sector's top quartile with steadier-than-median operating margins", src))
    if g("rev_g1") is not None and g("inc_gm") is not None:
        used += 1
        if g("rev_g1") < 0 and g("inc_gm") < 0: m -= 1; ev.append(("moat", f"Revenue {g('rev_g1'):+.0%} YoY with gross margin down {g('inc_gm')*100:+.1f} pp: possible disruption", src))
    if g("rev_g3") is not None:
        used += 1
        if g("rev_g3") < 0: m -= 1; ev.append(("moat", f"3-year revenue CAGR {g('rev_g3'):+.1%}", src))
    s["moat"] = m if used >= 2 else 0
    if used < 2: thin.append("moat")
    # 2. hidden stakes (XBRL non-operating investments vs market cap)
    st = 0; nop, mcap = g("non_op_inv"), g("mcap")
    if nop is not None and mcap and mcap > 0 and nop > 0:
        r = nop / mcap; st = 3 if r >= 0.5 else 2 if r >= 0.25 else 1 if r >= 0.10 else 0
        if st: ev.append(("stakes", f"Investments outside operations ${nop/1e9:,.1f}B = {r:.0%} of market cap (XBRL LongTermInvestments / EquityMethodInvestments / ShortTermInvestments)", src))
    else: thin.append("stakes")
    s["stakes"] = st
    # 3. talent density & R&D
    t_ = 0; rdi, roi = g("rd_int"), g("rd_roi")
    if rdi is not None and rdi > 0 and roi is not None:
        if rdi >= (ctx.get("rdi50") or 1e9) and roi > 0: t_ += 1; ev.append(("talent", f"R&D {rdi:.0%} of revenue (≥ sector median) with positive revenue return on R&D", src))
        if roi >= (ctx.get("roi75") or 1e9): t_ += 1; ev.append(("talent", f"Revenue growth per $ of prior-year R&D {roi:.2f}× (top quartile)", src))
        if roi < 0: t_ -= 1; ev.append(("talent", f"Revenue fell despite R&D spend (rd_roi {roi:.2f})", src))
    else: thin.append("talent")
    s["talent"] = t_
    # 4. pricing power & backlog
    p = 0; ig, dr, rg = g("inc_gm"), g("def_rev_g1"), g("rev_g1")
    if ig is not None:
        if ig > 0: p += 1; ev.append(("pricing", f"Gross margin up {ig*100:.1f} pp YoY", src))
        if ig < -0.02: p -= 1; ev.append(("pricing", f"Gross margin down {ig*100:.1f} pp YoY", src))
    if dr is not None:
        if rg is not None and dr > rg and dr > 0: p += 1; ev.append(("pricing", f"Deferred revenue / contract liabilities {dr:+.0%} YoY, ahead of revenue {rg:+.0%} (backlog building)", src))
        if dr < -0.10: p -= 1; ev.append(("pricing", f"Deferred revenue / contract liabilities {dr:+.0%} YoY", src))
    if ig is None and dr is None: thin.append("pricing")
    s["pricing"] = max(-2, min(2, p))
    # 5. variant perception gap (quality/growth rank vs cheapness rank)
    v = 0
    if ctx.get("S1") is not None and ctx.get("S3") is not None and ctx.get("S2") is not None:
        gap = (ctx["S1"] + ctx["S3"]) / 2 - (1 - ctx["S2"])
        v = 2 if gap >= 0.30 else 1 if gap >= 0.15 else -2 if gap <= -0.30 else -1 if gap <= -0.15 else 0
        ev.append(("variant", f"Quality/growth rank {(ctx['S1']+ctx['S3'])/2:.0%} vs valuation-implied rank {1-ctx['S2']:.0%} in its sector (gap {gap:+.2f})", src))
    else: thin.append("variant")
    s["variant"] = v
    return s, ev, thin

def apply_notes(t, s, ev):
    f = NOTES / f"{t}.json"
    if not f.exists(): return s, ev, None
    n = json.load(open(f)); used = []
    for k, o in (n.get("scores") or {}).items():
        if k in RANGES and o.get("sources"):
            lo, hi = RANGES[k]; s[k] = int(max(lo, min(hi, o["value"]))); used.append(k)
            ev.append((k, o.get("why", "analyst note"), o["sources"][0]))
    return s, ev, {"used": used, "sotp_usd": n.get("sotp_usd") if n.get("sotp_sources") else None, "sotp_sources": n.get("sotp_sources")}

def text_fields(t, row, s, ev, filings, ctx):
    g = lambda k: _nz(row.get(k))
    ey, sec_ey = g("ey_adj_ev"), ctx.get("ey_med")
    if ey and ey > 0 and sec_ey and sec_ey > 0:
        consensus = f"Market prices it at {1/ey:.0f}× adjusted-EV/EBIT vs a sector median near {1/sec_ey:.0f}×, i.e. {'a premium' if ey < sec_ey else 'a discount'} to peers."
    elif ey is not None and ey <= 0:
        consensus = "No positive operating earnings (EBIT), so the price rests on future profits."
    else:
        consensus = "Too little data to read the market-implied multiple."
    pos = [e[1] for e in ev if e[0] in ("moat", "pricing", "talent", "stakes") and not e[1].startswith(("Revenue fell", "Gross margin down", "3-year revenue", "Deferred revenue / contract liabilities -"))]
    variant = (f"Variant gap {s['variant']:+d}: " + (pos[0] if pos else "no clear business-quality edge in the filings")) if s["variant"] > 0 else \
              (f"Variant gap {s['variant']:+d}: valuation already prices in more quality/growth than the filings show" if s["variant"] < 0 else "No clear gap between valuation and business quality.")
    threats = []
    if g("rev_g1") is not None and g("rev_g1") < 0: threats.append(f"revenue {g('rev_g1'):+.0%} YoY")
    if g("inc_gm") is not None and g("inc_gm") < -0.02: threats.append(f"gross margin {g('inc_gm')*100:+.1f} pp")
    if g("lev") is not None and g("lev") > 0.5: threats.append(f"debt {g('lev'):.0%} of assets")
    if g("dil_1y") is not None and g("dil_1y") > 0.03: threats.append(f"share count {g('dil_1y'):+.0%} YoY")
    if any(("4.02" in (f.get("items") or "")) for f in filings): threats.append("an 8-K item 4.02 (non-reliance on prior financials)")
    cats = []
    for f in filings[:6]:
        if f["form"] == "8-K":
            its = [ITEM_8K.get(i.strip()) for i in (f.get("items") or "").split(",") if ITEM_8K.get(i.strip()) and i.strip() not in ("9.01",)]
            if its: cats.append(f"{f['date']} 8-K: {', '.join(its)}")
        elif f["form"] in ("10-K", "10-Q"): cats.append(f"{f['date']} {f['form']} filed")
    if ctx.get("next_earn"): cats.insert(0, f"next results expected about {ctx['next_earn']} (estimate from SEC filing history)")
    return consensus, variant, ("; ".join(threats) or "none flagged in the filings data"), ("; ".join(cats[:4]) or "no recent filings found")

def build_one(t, row, ctx, force=False):
    DOSS.mkdir(parents=True, exist_ok=True)
    f = DOSS / f"{t}.json"
    if f.exists() and not force:
        d = json.load(open(f))
        if (dt.date.today() - dt.date.fromisoformat(d["built"])).days < TTL_DAYS: return d
    s, ev, thin = score(row, ctx)
    s, ev, note = apply_notes(t, s, ev)
    filings, sub_url = recent_filings(ctx["cik"]) if ctx.get("cik") else ([], None)
    cons, var, thr, cat = text_fields(t, row, s, ev, filings, ctx)
    f_strat = max(-10, min(10, sum(s.values())))
    sources = sorted({e[2] for e in ev if e[2]} | ({sub_url} if sub_url else set()) | {x["url"] for x in filings[:6]})
    d = {"t": t, "built": dt.date.today().isoformat(), "ttl_days": TTL_DAYS, "scores": s, "f_strat": f_strat,
         "thin": thin, "evidence": [{"k": k, "claim": c, "src": u} for k, c, u in ev],
         "consensus_view": cons, "variant_edge": var, "top_threats": thr, "catalysts": cat,
         "filings": filings[:6], "sources": sources, "note": note,
         "method": "Rule-based from SEC filings data (no LLM); unvalidated overlay, not point-in-time."}
    json.dump(d, open(f, "w"), indent=1)
    return d

def contexts(cur, U, sleeves_now, cik_of, next_earn):
    """Sector reference points for the rules (current top-1000 universe)."""
    q = {}
    for sec, g in U.groupby("sector"):
        r = g[g.rd_int > 0]
        q[sec] = {"gm75": _nz(g.gm.quantile(.75)), "oms50": _nz(g.om_stab.median()), "ey_med": _nz(g.ey_adj_ev.median()),
                  "rdi50": _nz(r.rd_int.median()) if len(r) >= 5 else None, "roi75": _nz(r.rd_roi.quantile(.75)) if len(r) >= 5 else None}
    def ctx(t):
        sec = cur.loc[t, "sector"] if t in cur.index else None
        c = dict(q.get(sec, {})); c["cik"] = cik_of.get(t); c["next_earn"] = next_earn.get(t)
        if t in sleeves_now.index:
            for k in ("S1", "S2", "S3"): c[k] = _nz(sleeves_now.loc[t, k])
        return c
    return ctx
