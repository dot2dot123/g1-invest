#!/usr/bin/env bash
# Fast single-page build: reuse build/data/shared.json (from the last full build_site.py run), rebuild this page's
# isolated data, render and encrypt it. Usage: scripts/deploy_user.sh <slug>. Then review, git add <output_path>index.html, commit, push.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
SLUG="${1:?usage: deploy_user.sh <slug>}"
[[ -f "$ROOT/build/data/shared.json" ]] || { echo "Run pipeline/build_site.py once first (creates build/data/shared.json)" >&2; exit 1; }
cd "$ROOT/pipeline"
"$PY" build_site.py --site-only --page "$SLUG"
"$PY" render.py --page "$SLUG"
"$ROOT/scripts/encrypt-pages.sh" "$SLUG"
