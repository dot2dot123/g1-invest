#!/usr/bin/env bash
# Encrypt every configured page (config/users.json) from build/clear/ with StatiCrypt, each with its own password file.
# Passwords are read from files (never hardcoded, never printed). Usage: scripts/encrypt-pages.sh [SLUG]
# G1_NO_ENCRYPT=1 scripts/encrypt-pages.sh  -> TEMPORARY: publish the cleartext pages without a password (owner request only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
ONLY="${1:-}"
if [[ ! -f .staticrypt.json ]]; then
  SALT="$(node -e "console.log(require('crypto').randomBytes(16).toString('hex'))")"
  printf '{\n  "options": {\n    "salt": "%s"\n  }\n}\n' "$SALT" > .staticrypt.json
fi
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
n=0
while IFS='|' read -r slug out pass_file; do
  [[ -z "$ONLY" || "$ONLY" == "$slug" ]] || continue
  if [[ "${G1_NO_ENCRYPT:-0}" == "1" ]]; then
    clear="build/clear/${out}index.html"; dest="$ROOT/${out}index.html"
    [[ -f "$clear" ]] || { echo "Run pipeline/render.py first ($clear missing)" >&2; exit 1; }
    mkdir -p "$(dirname "$dest")"; cp "$clear" "$dest"; echo "UNENCRYPTED (G1_NO_ENCRYPT=1) -> ${out}index.html"
    n=$((n+1)); continue
  fi
  [[ -f "$pass_file" ]] || { echo "Missing password file for page $slug" >&2; exit 1; }
  PASSWORD="$(tr -d '\r\n' < "$pass_file")"
  [[ -n "$PASSWORD" ]] || { echo "Password file is empty for page $slug" >&2; exit 1; }
  clear="build/clear/${out}index.html"; dest="$ROOT/${out}index.html"
  [[ -f "$clear" ]] || { echo "Run pipeline/render.py first ($clear missing)" >&2; exit 1; }
  export STATICRYPT_PASSWORD="$PASSWORD"
  encrypt_one "$clear" "$dest"
  unset STATICRYPT_PASSWORD PASSWORD
  # Leak guard: the published file must not contain cleartext page data.
  if grep -q -E 'g1data|"rows":|"tmeta":|"books":|"tick":|"models":|OTW_holdings' "$dest"; then echo "LEAK CHECK FAILED in ${out}index.html" >&2; exit 1; fi
  n=$((n+1))
done < <(cd pipeline && "$PY" -c 'from build_site import load_config
for p in load_config(): print(p["slug"], p["output_path"], p["password_file"], sep="|")')
if [[ "${G1_NO_ENCRYPT:-0}" == "1" ]]; then echo "Published $n page(s) WITHOUT encryption."; else echo "Leak check passed ($n page(s))."; fi
