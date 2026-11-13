# G1 · Gary A

Personal multi-horizon (6/12/24/36/48/60-month) stock research dashboard. **Personal use only — not financial advice.**

The published pages (`/` and `/otw/`) are StatiCrypt-encrypted. No plaintext predictions, holdings, or model data are stored in this repository; `build/` and `cache/` are gitignored.

* `pipeline/` — data download (Yahoo prices, SEC EDGAR, S&P membership), point-in-time panels, walk-forward backtests, the G1 v2 composite, Buffett & Munger and Magic 15 style scores, page render.
* `docs/REBUILD_GUIDE.md` — how the whole system works and how to rebuild it. `docs/PREREGISTRATION*.md` — rules committed before each test.
* `web/` — dashboard template and browser code. The Refresh button fetches live Yahoo prices in the browser (AllOrigins fallback for CORS) and re-scores with the model embedded in the encrypted page. There are no scheduled jobs or workflows.
* `scripts/encrypt-pages.sh` — encrypts `build/clear/*` into the published pages and checks for leaks.
* `scripts/rebuild.sh` — full data refresh + retrain (run manually only).
