"""On-demand dossier helper: python analyze_ticker.py T
Prints the cached dossier for T (30-day cache) or, if missing/stale, the exact brief for the bot to run (1 web search +
structured JSON), which is then saved with `python intel_dossiers.py --ingest FILE.json`. No paid API is called."""
import sys, json
import intel_dossiers as I

if __name__ == "__main__":
    t = sys.argv[1].upper().replace("-", ".")
    d = I.load(t)
    if d and not I.stale(t):
        print(t, "f_strat", d["f_strat"], d["scores"], "flags", d.get("flags"), "thin:", d.get("thin"))
        print("  bull:", d["bull_case"]); print("  bear:", d["bear_case"])
    else:
        print(f"No fresh dossier for {t}. Ask the bot to run this brief, then ingest the JSON:\n")
        print(I.brief(t))
