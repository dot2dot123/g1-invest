#!/usr/bin/env bash
# Encrypt the cleartext pages in build/clear/ with StatiCrypt for GitHub Pages.
# Password is read from the box secrets file (never hardcoded, never printed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PASS_FILE="${G1_DASHBOARD_PASSWORD_FILE:-/home/box/agent-data/secrets/danelfin-dashboard-password}"
[[ -f "$PASS_FILE" ]] || { echo "Missing password file" >&2; exit 1; }
PASSWORD="$(tr -d '\r\n' < "$PASS_FILE")"
[[ -n "$PASSWORD" ]] || { echo "Password file is empty" >&2; exit 1; }
[[ -f build/clear/index.html && -f build/clear/otw/index.html ]] || { echo "Run pipeline/render.py first" >&2; exit 1; }
if [[ ! -f .staticrypt.json ]]; then
  SALT="$(node -e "console.log(require('crypto').randomBytes(16).toString('hex'))")"
  printf '{\n  "options": {\n    "salt": "%s"\n  }\n}\n' "$SALT" > .staticrypt.json
fi
export STATICRYPT_PASSWORD="$PASSWORD"
encrypt_one() {
  local clear_html="$1" dest_html="$2" tmp produced
  tmp="$(mktemp -d)"
  npx --yes staticrypt "$clear_html" -d "$tmp" -c .staticrypt.json --remember 14 --short \
    --template-title "Gary A · G1" \
    --template-instructions "Enter the shared password to view this personal research dashboard." \
    --template-button "Unlock" --template-placeholder "Password" --template-remember "Remember for 14 days" \
    --template-color-primary "#3b82f6" --template-color-secondary "#0f172a" >/dev/null
  produced="$(find "$tmp" -type f -name '*.html' | head -1)"
  [[ -n "$produced" && -f "$produced" ]] || { echo "Encrypted output missing for $clear_html" >&2; rm -rf "$tmp"; exit 1; }
  mkdir -p "$(dirname "$dest_html")"; cp "$produced" "$dest_html"; rm -rf "$tmp"
  echo "encrypted -> ${dest_html#$ROOT/}"
}
encrypt_one build/clear/index.html "$ROOT/index.html"
encrypt_one build/clear/otw/index.html "$ROOT/otw/index.html"
unset STATICRYPT_PASSWORD PASSWORD
# Leak guard: published files must not contain cleartext model data or tickers' scores.
for f in index.html otw/index.html; do
  if grep -q -E 'g1data|"tick":|"models":|OTW_holdings' "$f"; then echo "LEAK CHECK FAILED in $f" >&2; exit 1; fi
done
echo "Leak check passed."
