# G1 Cloudflare Workers (optional, free tier)

Two Workers live in this folder. Nothing here is deployed automatically. Deploy needs a free Cloudflare account and `npx wrangler login` (browser OAuth) on the machine doing the deploy. There is no custom domain and no paid plan.

After a Worker is live, its URL looks like `https://<name>.<account>.workers.dev`.

## 1. Site reverse proxy (`site-proxy.js`) — hide the GitHub Pages origin, cache, DDoS

Serves `https://dot2dot123.github.io/g1-invest/*` from the Worker's root:

- `https://g1-site-proxy.<account>.workers.dev/` → main dashboard
- `https://g1-site-proxy.<account>.workers.dev/otw/` → OTW page

The Worker caches GET responses at the edge for ~10 minutes (Cache API + `Cache-Control: public, max-age=600`). HTML is passed through unchanged except for `href`/`src`/`action` attributes that point at the GitHub Pages origin or `/g1-invest/…`, so StatiCrypt's password shell and ciphertext keep working. Cloudflare's free DDoS protection comes with the Worker.

### Deploy

```bash
cd /path/to/g1-invest
npx wrangler login
npx wrangler deploy --config workers/wrangler.toml
```

Wrangler prints the `*.workers.dev` URL. Open `/` and `/otw/` and confirm each still shows the StatiCrypt password prompt (and no plaintext table). The GitHub Pages URLs keep working too; this proxy sits in front, it does not replace the origin.

## 2. CORS proxy (`cors-proxy.js`) — reliable live prices

The pages fetch live prices in the browser. Yahoo does not send CORS headers, so the page tries, in order:
**your own proxy** (if configured) → Yahoo directly → corsproxy.io → codetabs → AllOrigins (each with a timeout; the last working route is tried first next time).
Free public proxies are sometimes slow or down; your own Worker is the reliable option.

### Deploy

```bash
cd /path/to/g1-invest
npx wrangler login
npx wrangler deploy --config workers/wrangler.cors-proxy.toml
```

Or in the dashboard: *Workers & Pages* → *Create* → *Create Worker*, name it e.g. `g1-cors-proxy`, paste `workers/cors-proxy.js`, *Deploy*.

1. Note the URL, e.g. `https://g1-cors-proxy.<account>.workers.dev`.
2. Test: `curl -H "Origin: https://dot2dot123.github.io" "https://g1-cors-proxy.<account>.workers.dev/?url=https%3A%2F%2Fquery1.finance.yahoo.com%2Fv8%2Ffinance%2Fchart%2FAAPL%3Frange%3D5d%26interval%3D1d"` → JSON. Without the Origin header → 403.
3. If the dashboard itself is also served through the site-proxy Worker, add that origin to `ORIGINS` in `cors-proxy.js` (e.g. `https://g1-site-proxy.<account>.workers.dev`) and redeploy the CORS Worker, otherwise the browser will be rejected.
4. Put the CORS URL in `config/users.json` as `"proxy_url": "https://g1-cors-proxy.<account>.workers.dev"` (or export `G1_PROXY_URL=...`), then rebuild the pages without re-downloading data: `cd pipeline && ../.venv/bin/python build_site.py --site-only && ../.venv/bin/python render.py`, then `scripts/encrypt-pages.sh` (do **not** set `G1_NO_ENCRYPT`). Commit the encrypted `index.html` and `otw/index.html`.

## Security

- Site proxy: only forwards the GitHub Pages `g1-invest` tree; no secrets, no logging, no storage.
- CORS proxy: origin-locked (default `https://dot2dot123.github.io`; add the site-proxy origin if used). Only forwards Yahoo `v8/finance/chart` and SEC `api/xbrl/companyfacts` URLs; everything else is rejected.
- Free tier: 100k requests/day.
