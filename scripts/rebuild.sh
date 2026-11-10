#!/usr/bin/env bash
# Full rebuild (run only when Gary asks): refresh prices + SEC data, rebuild panel, retrain, score, render, encrypt.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT/pipeline"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
"$PY" fetch_prices.py ../cache/universe_all.txt --force
"$PY" fetch_edgar.py ../cache/universe_all.txt
"$PY" features.py
rm -f ../cache/model_results.json
"$PY" model.py 6,12,24,36,48,60
"$PY" build_site.py
"$PY" render.py
"$ROOT/scripts/encrypt-pages.sh"
