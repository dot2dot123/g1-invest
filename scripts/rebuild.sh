#!/usr/bin/env bash
# Full rebuild (manual only, when Gary asks). Free data only; makes no Danelfin calls. See docs/REBUILD_GUIDE.md.
# Order: universe -> prices -> SEC data -> panels -> backtests -> page data -> render -> encrypt.
# Steps 3b (bulk SEC zips, ~3 GB) and the wide price fetch are slow; set SKIP_BULK=1 to reuse what is already on disk.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT/pipeline"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
BULK="${G1_BULK_DIR:-/workspace/g1-bulk}"
"$PY" fetch_universe.py --bulk "$BULK"                       # 1. S&P history, current S&P, SEC ticker maps, wide candidates, ^TNX
"$PY" fetch_macro.py                                          # 1b. FRED keyless CSVs (HY OAS, 10y-2y) for Market Weather
"$PY" fetch_form4.py --bulk "$BULK"                           # 1c. SEC insider-transaction bulk sets -> Form 4 purchase clusters
"$PY" fetch_prices.py ../cache/universe_all.txt --force       # 2a. Yahoo daily prices, v1 universe (refresh)
"$PY" fetch_prices.py "$BULK/wide_need.txt"                    # 2b. Yahoo daily prices, wide names not yet cached
"$PY" fetch_edgar.py ../cache/universe_all.txt                # 3a. SEC companyfacts + submissions per CIK (v1 universe)
if [[ "${SKIP_BULK:-0}" != "1" ]]; then
  "$PY" fetch_bulk.py --bulk "$BULK" --force                  # 3b. SEC bulk zips -> per-ticker files for the wide universe
fi
"$PY" features_v2.py                                          # 4b. wide top-1000 panel -> cache/panel_v2.parquet
"$PY" model_v2.py                                             # 5b. G1 v2 composite (A) + ridge (B) walk-forward
"$PY" style_test.py                                           # 5c. Buffett & Munger / Magic 15 pressure test
"$PY" lean_test.py                                            # 5d. lean Magic 15 test
"$PY" model_v4.py                                             # 5e. G1 v4 pre-registered test (S_quant vs A; failed, kept for the record)
"$PY" model_v42.py                                            # 5f. G1 v4.2 pre-registered test (V42 vs A) -> oos_v42_*, model_v42_results.json (LIVE)
"$PY" model_v42_3m.py                                         # 5g. G1 v4.2 3-month test (V42 vs A) -> oos_v42_3.parquet, model_v42_3m_results.json (strip only)
"$PY" build_site.py                                           # 6. shared bundle + per-page data + dossiers (gitignored build/data/)
"$PY" render.py                                               # 7. cleartext pages for every config/users.json page (gitignored build/clear/)
"$ROOT/scripts/encrypt-pages.sh"                              # 8. StatiCrypt each page with its own password file + leak check
echo "Now: review, git add the encrypted index.html files, commit, push; then run scripts/verify_live.py"
