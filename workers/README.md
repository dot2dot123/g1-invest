# G1 CORS proxy (optional, free Cloudflare Worker)

The pages fetch live prices in the browser. Yahoo does not send CORS headers, so the page tries, in order:
**your own proxy** (if configured) → Yahoo directly → corsproxy.io → codetabs → AllOrigins (each with a timeout; the last working route is tried first next time).
Free public proxies are sometimes slow or down; your own Worker is the reliable option. Nothing here is deployed automatically.

A site reverse proxy was considered and then cancelled; it is not in this repo.

## Deploy (free Cloudflare account; done by Gary, not by the bot)

```bash
cd /path/to/g1-invest
npx wrangler login
npx wrangler deploy --config workers/wrangler.cors-proxy.toml
```

Or in the dashboard: *Workers & Pages* → *Create* → *Create Worker*, name it e.g. `g1-cors-proxy`, paste `workers/cors-proxy.js`, *Deploy*.

1. Note the URL, e.g. `https://g1-cors-proxy.<account>.workers.dev`.
2. Test: `curl -H "Origin: https://dot2dot123.github.io" "https://g1-cors-proxy.<account>.workers.dev/?url=https%3A%2F%2Fquery1.finance.yahoo.com%2Fv8%2Ffinance%2Fchart%2FAAPL%3Frange%3D5d%26interval%3D1d"` → JSON. Without the Origin header → 403.
3. Put the CORS URL in `config/users.json` as `"proxy_url": "https://g1-cors-proxy.<account>.workers.dev"` (or export `G1_PROXY_URL=...`), then rebuild the pages without re-downloading data: `cd pipeline && ../.venv/bin/python build_site.py --site-only && ../.venv/bin/python render.py`, then `scripts/encrypt-pages.sh` (do **not** set `G1_NO_ENCRYPT`). Commit the encrypted `index.html` and `otw/index.html`.

## Security

- Origin-locked to `https://dot2dot123.github.io` (change `ORIGINS` if the site moves).
- Only forwards Yahoo `v8/finance/chart` and SEC `api/xbrl/companyfacts` URLs; everything else is rejected.
- No secrets, no logging, no storage. Free tier: 100k requests/day.
