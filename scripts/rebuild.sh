#!/usr/bin/env bash
# Full rebuild (manual only, when Gary asks). Free data only; makes no Danelfin calls. See docs/REBUILD_GUIDE.md.
# Order: universe -> prices -> SEC data -> panels -> backtests -> page data -> render -> encrypt.
# Steps 3b (bulk SEC zips, ~3 GB) and the wide price fetch are slow; set SKIP_BULK=1 to reuse what is already on disk.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT/pipeline"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
BULK="${G1_BULK_DIR:-/workspace/g1-bulk}"
"$PY" fetch_universe.py --bulk "$BULK"                       # 1. S&P history, current S&P, SEC ticker maps, wide candidates, ^TNX
"$PY" fetch_prices.py ../cache/universe_all.txt --force       # 2a. Yahoo daily prices, v1 universe (refresh)
"$PY" fetch_prices.py "$BULK/wide_need.txt"                    # 2b. Yahoo daily prices, wide names not yet cached
"$PY" fetch_edgar.py ../cache/universe_all.txt                # 3a. SEC companyfacts + submissions per CIK (v1 universe)
if [[ "${SKIP_BULK:-0}" != "1" ]]; then
  "$PY" fetch_bulk.py --bulk "$BULK" --force                  # 3b. SEC bulk zips -> per-ticker files for the wide universe
fi
"$PY" features.py                                             # 4a. v1 panel (S&P members) -> cache/panel.parquet
rm -f ../cache/model_results.json
"$PY" model.py 6,12,24,36,48,60                               # 5a. v1 walk-forward + price-only models
"$PY" features_v2.py                                          # 4b. wide top-1000 panel -> cache/panel_v2.parquet
"$PY" model_v2.py                                             # 5b. G1 v2 composite (A) + ridge (B) walk-forward
"$PY" style_test.py                                           # 5c. Buffett & Munger / Magic 15 pressure test
"$PY" lean_test.py                                            # 5d. lean Magic 15 test
"$PY" build_site.py                                           # 6. page data (gitignored build/data/*.json)
"$PY" render.py                                               # 7. cleartext pages (gitignored build/clear/)
"$ROOT/scripts/encrypt-pages.sh"                              # 8. StatiCrypt -> index.html, otw/index.html + leak check
echo "Now: review, git add index.html otw/index.html, commit, push; then run scripts/verify_live.py"
