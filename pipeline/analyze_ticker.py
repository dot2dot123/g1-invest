"""On-demand business dossier for one ticker: python analyze_ticker.py T [--force]. Writes cache/dossiers/T.json
(14-day cache) and prints a short summary; the next build_site.py run ships it in the page."""
import sys, json
import build_site as B

if __name__ == "__main__":
    t = sys.argv[1].upper().replace("-", ".")
    d = B.dossiers_for([t], force="--force" in sys.argv).get(t)
    if not d: print("No fundamentals for", t, "in the current panel"); sys.exit(1)
    print(t, "f_strat", d["f_strat"], d["scores"], "thin:", d["thin"])
    for k in ("consensus_view", "variant_edge", "top_threats", "catalysts"): print(f"  {k}: {d[k]}")
