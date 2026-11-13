"""G1 v4.2 business dossiers: 1 web search + a structured-JSON analyst judgment per ticker (docs/PREREGISTRATION_V4_2.md).

How dossiers get made (no paid API):
  The repo has no LLM or search API key and G1 uses no paid services, so this script cannot call a model by itself.
  Dossiers are produced when Gary asks his Grok Bot: the bot runs ONE free web search per ticker, writes the judgment
  as JSON following PROMPT below, and saves it with `python intel_dossiers.py --ingest FILE.json` (FILE holds one
  dossier or a list). `python intel_dossiers.py --pending` lists names that are missing or older than 30 days
  (holdings in config/users.json + the G1 Top 30). `python analyze_ticker.py T` prints the brief for one name.

Cache: cache/dossiers/{T}.json (30-day TTL, gitignored). Gary's private notes: cache/dossiers/manual_overrides.json
(gitignored), e.g. {"MU": {"note": "...", "f_strat": 2, "bear_case": "..."}}. Any field there wins over the generated
dossier and survives every rebuild.

The overlay is NOT point-in-time and cannot be backtested: f_strat is an unvalidated secondary pill, never added into
the G1 Score, verdicts, sizes or stops."""
import json, sys, datetime as dt
from common import *

DOSS = CACHE / "dossiers"; OVR = DOSS / "manual_overrides.json"
TTL_DAYS = 30
SCHEMA = 2
RANGES = {"moat": (-2, 2), "hidden_stakes": (0, 3), "ai_threat": (-3, 1), "cyclical": (-3, 0), "pricing": (-2, 2), "variant": (-2, 2)}

PROMPT = """You are writing a G1 business dossier for {T} ({NAME}). Use ONE web search, then answer ONLY with JSON:
{
 "ticker": "{T}", "bull_case": "...", "bear_case": "...",          <- write BOTH cases first, before any score
 "scores": {"moat": -2..2, "hidden_stakes": 0..3, "ai_threat": -3..1, "cyclical": -3..0, "pricing": -2..2, "variant": -2..2},
 "flags": {"cyclical_peak": true|false, "hidden_sotp": "short text or null", "ai_threat": "short text or null"},
 "thin": ["sub-scores with too little evidence (score them 0)"],
 "sources": [{"title": "...", "url": "https://..."}]                <- every claim must come from a cited source
}
Rules:
- Never invent facts. If evidence for a sub-score is thin, score it 0 and list it in "thin".
- CYCLICAL PEAKS: memory/commodity chipmakers, miners, energy, shippers, chemicals, homebuilders, autos and similar at
  record or near-record margins with a single-digit or low P/E are cyclical peaks, NOT permanent moats. Set
  flags.cyclical_peak = true, cyclical = -2 or -3, and never give such names moat > +1 for the peak margins alone.
- HIDDEN SOTP STAKES: reward real, cited stakes the market under-counts (e.g. Waymo in Alphabet, Anthropic stakes in
  Amazon/Alphabet, listed holdings, spin-off candidates) with hidden_stakes +1..+3 and describe them in flags.hidden_sotp.
- AI / AGENTIC MOAT THREATS: penalize businesses whose moat is a seat-based or workflow product that AI agents can
  replace (e.g. Claude in Sheets vs Office, AI coding agents vs dev tools, agentic search vs ads/travel/directories):
  ai_threat -1..-3 with flags.ai_threat. Clear AI beneficiaries may get +1.
- f_strat is computed by the script as the clamped sum (-10..+10); do not output it."""

def _path(t): return DOSS / f"{t}.json"

def overrides():
    try: return json.load(open(OVR)) if OVR.exists() else {}
    except Exception: return {}

def finalize(d):
    """Validate, clamp and score one dossier dict (in place). f_strat = clamp(sum(sub-scores), -10, 10)."""
    s = d.setdefault("scores", {})
    for k, (lo, hi) in RANGES.items():
        v = s.get(k, 0)
        try: v = int(round(float(v)))
        except Exception: v = 0
        s[k] = max(lo, min(hi, v))
    d["thin"] = [k for k in d.get("thin", []) if k in RANGES]
    for k in d["thin"]: s[k] = 0
    d["f_strat"] = max(-10, min(10, sum(s.values())))
    d.setdefault("flags", {}); d["flags"].setdefault("cyclical_peak", False)
    d["thin_all"] = len(d["thin"]) >= 4 or not d.get("sources")
    if d["thin_all"]: d["f_strat"] = 0
    if not d.get("bull_case") or not d.get("bear_case"): raise ValueError(f"{d.get('ticker')}: bull_case and bear_case are required")
    d["sources"] = [x for x in d.get("sources", []) if isinstance(x, dict) and str(x.get("url", "")).startswith("http")]
    d["schema"] = SCHEMA
    d.setdefault("built", str(dt.date.today()))
    d.setdefault("method", "1 web search + analyst-style judgment (Grok Bot), unvalidated")
    return d

def ingest(path):
    data = json.load(open(path)); data = data if isinstance(data, list) else [data]
    DOSS.mkdir(parents=True, exist_ok=True); n = 0
    for d in data:
        d = finalize(dict(d)); t = d["ticker"].upper().replace("-", ".")
        d["ticker"] = t; json.dump(d, open(_path(t), "w"), indent=1); n += 1
    print("ingested", n, "dossiers")

def load(t, apply_overrides=True):
    f = _path(t)
    if not f.exists(): return None
    try: d = json.load(open(f))
    except Exception: return None
    if d.get("schema") != SCHEMA: return None
    o = overrides().get(t) if apply_overrides else None
    if o:
        d = dict(d); d.update({k: v for k, v in o.items() if k != "scores"})
        if "scores" in o: d["scores"] = dict(d.get("scores", {}), **o["scores"]); 
        if "f_strat" not in o and "scores" in o: d["f_strat"] = max(-10, min(10, sum(d["scores"].values())))
        d["override"] = True
    return d

def load_all():
    out = {}
    for f in DOSS.glob("*.json"):
        if f.name == OVR.name: continue
        d = load(f.stem)
        if d: out[f.stem] = d
    for t, o in overrides().items():   # a note on a name without a generated dossier still shows up
        if t not in out and o.get("bull_case") and o.get("bear_case"):
            out[t] = finalize(dict(o, ticker=t, method="Gary's manual notes"))
    return out

def stale(t, today=None):
    d = load(t, False)
    if not d: return True
    today = today or dt.date.today()
    return (today - dt.date.fromisoformat(d["built"])).days > TTL_DAYS

def wanted():
    import build_site as B
    S = json.load(open(ROOT / "build" / "data" / "shared.json"))
    w = set(S["finalists"])
    for p in B.load_config():
        for path in p["books"].values(): w |= {x["t"] for x in B.read_book(path, False)}
    return sorted(w), S

def brief(t, S=None):
    name = (S["tmeta"].get(t) or [None] * 7)[6] if S else ""
    return PROMPT.replace("{T}", t).replace("{NAME}", name or t)

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--ingest": ingest(a[1])
    elif a and a[0] == "--pending":
        w, S = wanted(); p = [t for t in w if stale(t)]
        print(len(p), "of", len(w), "dossiers missing or older than", TTL_DAYS, "days")
        if "--names" in a: print(" ".join(p))
    else: print(__doc__)
