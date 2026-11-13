# G1 CORS proxy (optional)

The pages fetch live prices in the browser. Yahoo does not send CORS headers, so the page tries, in order:
**your own proxy** (if configured) → Yahoo directly → corsproxy.io → codetabs → AllOrigins (each with a timeout; the last working route is tried first next time).
Free public proxies are sometimes slow or down; your own Worker is the reliable option. Nothing here is deployed automatically.

## Deploy (free Cloudflare account, ~5 minutes; done by Gary, not by the bot)
1. Sign up at https://dash.cloudflare.com (free plan) → *Workers & Pages* → *Create* → *Create Worker*, name it e.g. `g1-proxy`.
2. Replace the editor contents with `workers/cors-proxy.js` → *Deploy*. (CLI alternative: `npm i -g wrangler && wrangler login && wrangler deploy workers/cors-proxy.js --name g1-proxy --compatibility-date 2026-11-01`.)
3. Note the URL, e.g. `https://g1-proxy.<you>.workers.dev`.
4. Test: `curl -H "Origin: https://dot2dot123.github.io" "https://g1-proxy.<you>.workers.dev/?url=https%3A%2F%2Fquery1.finance.yahoo.com%2Fv8%2Ffinance%2Fchart%2FAAPL%3Frange%3D5d%26interval%3D1d"` → JSON. Without the Origin header → 403.
5. Put it in `config/users.json` as `"proxy_url": "https://g1-proxy.<you>.workers.dev"` (or export `G1_PROXY_URL=...`), then rebuild the pages without re-downloading data: `cd pipeline && ../.venv/bin/python build_site.py --site-only && ../.venv/bin/python render.py`, encrypt/publish as usual.

## Security
- Origin-locked to `https://dot2dot123.github.io` (change `ORIGINS` if the site moves).
- Only forwards Yahoo `v8/finance/chart` and SEC `api/xbrl/companyfacts` URLs; everything else is rejected.
- No secrets, no logging, no storage. Free tier: 100k requests/day.
