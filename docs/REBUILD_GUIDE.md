# G1 rebuild guide

This guide explains how G1 works and how to rebuild it from scratch. It is written from the code in this repo (`dot2dot123/g1-invest`) and the helper files on the bot's box. It contains no secrets: no password, no API key, no holdings and no prediction data.

G1 is for Gary A's personal research only. It is not financial advice.

---

## 00. G1 v4.2 (current; added 2026-11-12 PST). Where this section conflicts with any later section, this section wins.

**Live score = V42** (`pipeline/model_v42.py`, pre-registered in `docs/PREREGISTRATION_V4_2.md`, commit 27e9cd6 before any result; results appended in c13ea6e).
- P1 = universe percentile of Buffett & Munger points (0–10); P2 = universe percentile of lean Magic 15; P3 = mean within-sector percentile of `ey_hist_med` (5y median EBIT/EV) and `fcfy_ev`; P4 = mean of within-sector percentile of `mom_12_1` and 1 − universe percentile of `beta_down`.
- blend = mean(P1..P4); V = percentile of blend; if B&M < 4 then V ≤ 0.65; score = 100·V. No fitted parameters.
- Browser mirror: `v42Of()` in `web/app.js` uses shipped 101-point quantiles `meta.v42q` (`bm`, `l15`, `beta_down`, `blend`, per-sector `ey_hist_med`/`fcfy_ev`/`mom_12_1`). Python mirror `v42_parts()/v42_score()` in `build_site.py`; `build/data/parity.json` checks them.
- Pass rule: rank IC beats A at ≥ 4/6 horizons AND hysteresis turnover ≤ 1.2× A, where holdings H_t = {pct > 0.85} ∪ (H_{t−1} ∩ {pct > 0.65}).

| h | V42 IC (t) | A IC (t) | V42 TMB | A TMB |
|---|---|---|---|---|
| 6m | .047 (2.23) | .036 (2.41) | +.004 | +.015 |
| 12m | .061 (2.27) | .049 (2.24) | −.006 | +.022 |
| 24m | .092 (2.83) | .076 (2.20) | −.007 | +.035 |
| 36m | .116 (4.05) | .090 (2.39) | +.003 | +.057 |
| 48m | .132 (4.38) | .104 (2.64) | +.047 | +.117 |
| 60m | .125 (3.23) | .108 (2.76) | +.053 | +.126 |

Hysteresis turnover V42 0.031 vs A 0.048 (0.65×) → **PASS, V42 live**. Caveat: V42's top-minus-bottom spread is much smaller than A's (it ranks the whole list better, the extreme decile less sharply).

**Execution rules (prereg §4; UI rules, not backtested; "model estimates, not advice").** Q = G1 Score; Upside/Safety = percentiles of U and D among the top-1000 (`meta.pq.U/.D`; QA fix 2026-11-12: the raw sleeve averages are compressed to ~10–80, so the 70/60/65 thresholds were unreachable).
- STRONG BUY: Q ≥ 75, Upside ≥ 70, Safety ≥ 60, price > 40w SMA, 1m return ≤ 15%. ACCUMULATE (Staggered): same with 1m > 15%.
- WAIT FOR TREND (Pullback): Q ≥ 70, Upside ≥ 65, and price < SMA40 or > 20% below the 52w high. Shows the 10w-EMA Momentum Reclaim Trigger and the Deep-Value zone (price at the 5y-median EV/EBIT; shown as "already below" if that price is above today's, and marked unreliable for dossier cyclical-peak names).
- CLIMAX TRIM (needs an entry): gain ≥ 40%, price > 1.35× SMA40, weekly volume > 3× 52w median, close in the bottom half of the weekly range.
- SELL / BROKEN: price < SMA40 AND (Q < 45 OR (om_trend < 0 AND Q < 70)). QA fix: Q ≥ 70 is never "broken" on a margin dip alone.
- Price-only names (no SEC fundamentals: ETFs, some foreign listings) can only be HOLD or SELL (QA fix).
- HOLD otherwise. Bear Preservation pauses buys. Rebalance alerts only if a book CSV has shares and a weight drifts > 25% from equal weight.
- Stops: Initial Risk Stop = max(SMA40 if below price, P·(1+cvar_5) if cvar_5 < 0), always < price, else n/a. With an Entry $ (CSV EntryPrice/Cost column, or the inline input saved in localStorage `g1.positions.v1`): stage 2 breakeven at +20%, stage 3 10w-EMA trail at +40%.
- Size: edge = max(0, p − base rate 12m); r = edge / max(sigma_down, 0.12); r ≥ 0.40 High 6–8%, 0.20–0.40 Core 3–5%, 0–0.20 Starter 1–2%, else No edge. 0 for SELL/TRIM; halved for WAIT or earnings ≤ 7 days.
- Cash banner: equity = clamp(0.14 / SPY 1y daily downside vol, 0.5, 1), rest SGOV; in Bear Preservation equity = min(vm, 1 − reserve). `meta.weather.spy_dvol`, `eq_vm`.
- Python mirror `py_verdict()` (no entry → never TRIM) feeds the audit ledger; QA checks it equals the JS verdict for every ledger row.

**Business dossiers** (`pipeline/intel_dossiers.py`, schema 2). Produced only when Gary asks the bot: the bot runs one web search per ticker and writes structured JSON (bull_case and bear_case first, then sub-scores moat −2..2, hidden_stakes 0..3, ai_threat −3..1, cyclical −3..0, pricing −2..2, variant −2..2, flags, thin list, source URLs). `f_strat` = clamped sum (−10..+10); thin sub-scores count 0; ≥ 4 thin or no sources → f_strat 0. Shown as a separate "Dossier" pill, never added into the G1 Score.
- Workflow: `../.venv/bin/python intel_dossiers.py --pending --names` (holdings + top-30 finalists missing or older than 30 days) → bot writes batch files → `intel_dossiers.py --ingest FILE` → `cache/dossiers/{T}.json`. `analyze_ticker.py T` prints a dossier or the brief to run.
- `cache/dossiers/manual_overrides.json` (gitignored) wins over generated values. Old schema-1 files were moved to `cache/dossiers/_v4_old/`.
- No paid APIs. ETFs (e.g. sector funds) get no dossier.

**Live audit ledger.** `build_site.py` appends one row per (ISO week, ticker) for holdings + finalists to `cache/live_audit.jsonl` (gitignored; skip with `--no-audit`): week, date, quant_score, model, dossier_score, verdict, price. `scripts/track_signals.py` scores it later (forward excess return vs SPY at 4/13/26/52 weeks; IC of quant and dossier scores; hit rate by verdict). Manual only.

**Live prices / proxy.** Order: own proxy (`meta.proxy_url` from env `G1_PROXY_URL` or `config/users.json` `"proxy_url"`, empty by default) → Yahoo direct → corsproxy.io → codetabs → AllOrigins raw → AllOrigins get, each with a timeout; last working route first. Refresh uses 3 parallel requests on free proxies (6 with own proxy) plus one slower retry pass. Free proxies are unreliable (2026-11-12: corsproxy.io 401, codetabs 522, AllOrigins intermittent); the reliable fix is `workers/cors-proxy.js` (Cloudflare Worker, origin-locked, Yahoo chart + SEC companyfacts only; deploy steps in `workers/README.md`; not deployed by the bot).

**UI (v4.2 redesign).** Light theme (`web/style.css`), colour-coded verdict badges (`.v-buy/.v-acc/.v-wait/.v-trim/.v-sell/.v-hold`), Market Weather + Cash Plan banners side by side, table rows turn into cards under 760 px (`td[data-l]` labels). Help and method text in `web/template.html`. Disclaimers "Personal use only, not financial advice", proxy wording and "Gary A" must stay.

**Commands.**
- UI/logic only (no downloads): `cd pipeline && ../.venv/bin/python build_site.py --site-only && ../.venv/bin/python render.py`
- Publish unencrypted (current, at Gary's request): `G1_NO_ENCRYPT=1 scripts/encrypt-pages.sh`, then `git add index.html otw/index.html && git commit && git push`, then `scripts/verify_live.py` (expects no password screen when `G1_NO_ENCRYPT=1`).
- Re-encrypt when Gary asks: `scripts/encrypt-pages.sh && git add index.html otw/index.html && git -c user.name=dot2dot123 -c user.email=dot2dot123@users.noreply.github.com commit -m "Re-encrypt G1 pages" && git push`, then `.venv/bin/python scripts/verify_live.py`.
- Full rebuild: `scripts/rebuild.sh` (now includes `model_v42.py`).
- QA: Playwright (Chrome headless) over every tab of both pages at 1400 px and 375 px: NaN/undefined, console errors, horizontal overflow, Look Up, Entry $ → localStorage, JS vs `py_verdict` parity, stops below price, verdict/size distributions.

## 0. G1 v4 (superseded in part by section 00 / v4.2; added 2026-11-12). Where this section conflicts with later sections (other than 00), this section wins.

**What changed.**
- **Engine test.** A five-sleeve quant engine (S_quant) was pre-registered in `docs/PREREGISTRATION_V4.md` and tested against the v2 composite A. It FAILED, so A is still the live quant score. Everything else in v4 ships on top of A.
- **New page features:**
  - Market Weather & Cash Allocation banner
  - "Look Up Any Stock" report card for about 5,800 US tickers (bundled data, no wait)
  - six-column table: verdict, G1 Score, Upside/Safety bars, 1-yr win odds with a $ range, half-Kelly size
  - three-stage ratchet stops
  - Portfolio Health card (sector concentration over 35%, pairwise correlation over 0.80)
  - rule-based business dossiers
  - Danelfin sub-scores from the uploaded CSVs (owner pages only)
  - multi-user pages from `config/users.json`
- **Superseded draft.** `docs/PREREGISTRATION_V3.md` was superseded by v4 before any test.

**Pipeline additions** (all free data; scripts in `pipeline/`):
- **`fundamentals.py` + `features.py`.** New XBRL tags:
  - AssetsCurrent / LiabilitiesCurrent
  - R&D
  - LongTermInvestments / MarketableSecuritiesNoncurrent, EquityMethodInvestments, ShortTermInvestments / MarketableSecuritiesCurrent
  - ContractWithCustomerLiability / DeferredRevenue (and their current + noncurrent parts)
- **New features:** fcf_conv, fcfy_ev, fcfy_adj_ev, ey_adj_ev (adjusted EV = max(mcap + debt − cash − non-operating investments, 0.25·mcap)), inc_roic_3y, inc_gm, def_rev_g1, rd_roi, rule_of_40, Piotroski f_score, eq_assets, roe_stab, roic_5y_med, post_filing_drift (SEC filing date × Yahoo daily price/volume), vcp_ratio, up_down_vol_50d, beta_down, cvar_5, sigma_down, sma40_below, last_px_ord.
- **`features_v2.py`** keeps them in `cache/panel_v2.parquet` and adds `sic`. Runtime is about 30 minutes because the daily features are slower.
- **`fetch_macro.py`.** Keyless FRED CSVs `BAMLH0A0HYM2` and `T10Y2Y` go to `cache/fred.parquet`. The free HY OAS history starts 2023-11-13, so the backtest drops the HY clauses before then (pre-registered).
- **`fetch_form4.py`.** SEC Insider Transactions Data Sets (quarterly zips, about 14 MB each, 2013q1→latest) go to `cache/form4_buys.parquet` as (issuer CIK, filing date, owner). Only Form 4 code "P" purchases are kept.
  - form4_cluster = at least 3 distinct buyers in 90 days.
  - Note: recent quarters live under `/files/datastandardsinnovation/...`, older ones under `/files/structureddata/...`.
- **`model_v4.py`.** Sleeves S1–S5, sector momentum multiplier, regime (Risk-On / Neutral / Risk-Off), U, D, S_quant and S_price. It also computes the Shumway haircut labels, the 10 bps × 2 × turnover × h top-decile drag, and the pass rule. Writes `cache/model_v4_results.json` and `cache/oos_v4_{h}.parquet`.
- **`build_site.py`:**
  - `build/data/shared.json`: the any-ticker columnar bundle (`meta.cols` + `rows[t]` arrays, 6 significant digits), plus `tmeta[t]` = [sector index, has fundamentals, financial (SIC 6000–6799), S&P member, Form 4 cluster, top-1000, name].
  - The bundle also carries quantile tables `sq` (v4 within-sector, financials masked), `sqA` (A), `uq` (universe), `fq` (financials group) and `mq` (Magic 15), plus sector multipliers, score quantiles `pq`, decile bands `cal[h][model]` (haircut labels), weather, share-class aliases and finalists (top 30 by the live score).
  - One `build/data/page_<slug>.json` per configured page.
  - Flags: `--site-only` reuses `shared.json`; `--page SLUG`; `--no-dossiers`.
  - `live_scores()` is the Python mirror of `rawScores()` in `web/app.js`. It uses a left-to-right float sum (`fsum_js`), because Python ≥ 3.12 `sum()` uses compensated summation and differs from JS in the last bits.
- **`intel_dossiers.py` + `analyze_ticker.py T`:**
  - Rule-based dossiers from SEC data: the XBRL facts plus the SEC submissions API for recent 8-K/10-K/10-Q links. No LLM, no paid data.
  - Five sub-scores (moat −2..2, hidden stakes 0..3, talent/R&D −1..2, pricing/backlog −2..2, variant gap −2..2) sum to f_strat (clamped to ±10), plus one-line consensus, variant edge, threats and catalysts. Every claim has a source link; thin evidence scores 0.
  - Cached in `cache/dossiers/T.json` for 14 days. Built for the holdings in every configured book plus the top 30.
  - Optional cited analyst notes go in `cache/dossiers/notes/T.json` as `{"scores": {"moat": {"value": 1, "why": "…", "sources": ["https://…"]}}, "sotp_usd": …, "sotp_sources": [...]}`. A note only counts if it has sources.
  - S_v4 = clamp(base + 1.5·f_strat, 0, 100), shown as "v4*" and labelled unvalidated. Base = 100 × A's universe percentile while A is live.

**v4 test results** (wide top-1000, month-ends 2014+, haircut + drag labels; IC (t); last column = top-decile p10 S_quant / A):

| h | S_quant | A | U | D | S_price | p10 S_quant / A |
|---|---|---|---|---|---|---|
| 6m | 0.035 (1.54) | 0.036 (2.41) | 0.032 (1.41) | 0.021 (1.00) | 0.027 (0.81) | -0.217 / -0.223 |
| 12m | 0.041 (1.35) | 0.049 (2.24) | 0.031 (0.97) | 0.029 (1.02) | 0.022 (0.48) | -0.312 / -0.308 |
| 24m | 0.047 (1.20) | 0.076 (2.20) | 0.026 (0.67) | 0.056 (1.57) | 0.021 (0.32) | -0.438 / -0.414 |
| 36m | 0.075 (1.76) | 0.090 (2.39) | 0.056 (1.24) | 0.070 (2.12) | 0.046 (0.64) | -0.500 / -0.501 |
| 48m | 0.090 (1.83) | 0.104 (2.64) | 0.068 (1.22) | 0.088 (2.63) | 0.053 (0.59) | -0.585 / -0.575 |
| 60m | 0.078 (1.31) | 0.108 (2.76) | 0.054 (0.82) | 0.084 (1.99) | 0.033 (0.31) | -0.659 / -0.644 |

- **Pass rule:** S_quant beat A's IC at 0/6 horizons (needed 4); t > 2.5 at 12m/24m: False; better p10 at 2/6 (needed 4). **FAIL.**
- **Haircut never triggered.** The free-data panel contains no delisted names (every ticker still trades), so the Shumway haircut affected 0 rows.

**Execution rules in the browser** (model estimates, not advice; exact definitions in the pre-registration, section 11):
- **Verdict:** SELL / BROKEN → CLIMAX TRIM → ACCUMULATE (Staggered) → STRONG BUY → HOLD.
- **Half-Kelly:** from 12m decile odds and p90/|p10|, scaled by 0.25/σ_down, max 10%, halved within 7 days of the estimated earnings date (last-year SEC filing date + 364 days).
  - With current odds (top decile ≈ 44–46% to beat the S&P at 12m), half-Kelly is 0 for nearly every name. The page shows "0% · no edge".
- **Ratchet stop:** Stage 1 max(40-week SMA of closes, P·(1 + cvar_5)); Stage 2 breakeven at +20% (needs a purchase price); Stage 3 10-week EMA trail at +40%.
- **Market Weather:** Sunny / Cloudy / Storm Warning. Bear Preservation means a 30–50% SGOV reserve and paused buys. CAPITULATION BUY needs SPY ≥ 15% off its high, breadth crossing above 0.40 from below 0.35, and HY ≥ 0.5 pp below its 13-week peak.
  - HY, the curve and breadth are fixed at build time; SPY is recomputed live on Refresh.

**Multi-user pages:**
- `config/users.json` is gitignored. It holds local paths only: book CSVs and password files. `config/users.example.json` is the committed template.
- Each page has `slug`, `output_path` ("" for the root page, "otw/" for the OTW page), `title`, `h1`, `password_file`, `danelfin` (true only for Gary's pages), `show_sp500`, and `books` {label: csv path}.
- Today only Gary is configured, with slugs `gary` (root) and `gary-otw` (`otw/`), both using the existing password file.
- **To add a friend:**
  1. Create their password file under `/home/box/agent-data/secrets/` (never in the repo).
  2. Put their CSV somewhere outside the repo, as a `Ticker` column or headerless `Ticker`, `Ticker,Shares` or `Ticker,Shares,Cost` rows.
  3. Add a page entry with `danelfin: false` and an `output_path` such as `u/<slug>/`.
  4. Run `scripts/deploy_user.sh <slug>`. This takes seconds and reuses `build/data/shared.json`.
  5. `git add <output_path>index.html`, commit and push.
  6. Run `scripts/verify_live.py`.
- **Isolation:** a page file holds only its own books, Danelfin fields only if `danelfin: true`, and dossiers, earnings dates and weekly prices only for its own holdings plus the public top 30. The any-ticker bundle is public-data only.
- **Scripts:**
  - `scripts/encrypt-pages.sh [SLUG]` loops over the config, encrypts each page with its own password file and leak-checks each output (`g1data|"rows":|"tmeta":|"books":|"tick":|"models":|OTW_holdings`).
  - `scripts/verify_live.py` loops over the config, unlocks each page with its own password file and checks rows, the weather banner and page errors.

**Watchlist:** the localStorage key is still `g1.research.v1`. Old entries keep their ticker and name, and scores are recomputed from the bundle.

---

## 1. Architecture overview

```
                    (on the box, run by hand)                                   (GitHub Pages, static)
 free data ──► Python pipeline ──► cleartext page data ──► StatiCrypt ──► index.html + otw/index.html
  Yahoo        pipeline/*.py        build/data/*.json        encrypt        password shell only
  SEC EDGAR    cache/ (gitignored)  build/clear/*.html                      │
  Wikipedia                         (gitignored)                            ▼
  fja05680                                                    browser: unlock ► decrypt ► app.js
  Danelfin CSV exports (AI Score)                             Refresh / Look up ► Yahoo chart API
                                                              (AllOrigins proxy fallback) ► re-score
```

- **Offline pipeline.** It runs on the box under `/workspace/g1-invest`, only when Gary asks (`scripts/rebuild.sh`). It downloads free data, builds point-in-time monthly panels and runs the walk-forward backtests. It then computes everything the page needs: quantile tables, decile calibration tables and per-ticker inputs and scores. All of this sits in `cache/` and `build/`, both gitignored.
- **One self-contained HTML file per page.** `pipeline/render.py` inlines the CSS, the JS and the page-data JSON into `web/template.html`. `scripts/encrypt-pages.sh` then encrypts the result with StatiCrypt. Only the encrypted files `index.html` and `otw/index.html` are committed.
- **In-browser Refresh.** After unlocking, the page can pull live weekly prices from Yahoo and recompute the price-dependent inputs. It re-scores with the same math as Python. There is no server, no GitHub Actions workflow, no cron and no polling.
- **Two URLs.**
  - Main page: `https://dot2dot123.github.io/g1-invest/`. Tabs: S&P 500, OTW, OTW #2, SWB, Jette, NEW and Research.
  - OTW page: `https://dot2dot123.github.io/g1-invest/otw/`. Tabs: OTW, OTW #2 and Research.

### Repo layout

| Path | Committed? | Purpose |
|---|---|---|
| `pipeline/common.py` | yes | Paths, User-Agents, book file names, horizons, S&P membership loader |
| `pipeline/fetch_universe.py` | yes | S&P history, current S&P, SEC ticker maps, wide candidate list, 10y Treasury |
| `pipeline/fetch_prices.py` | yes | Yahoo daily prices per ticker → `cache/prices/{T}.parquet` |
| `pipeline/fetch_edgar.py` | yes | SEC companyfacts + submissions per CIK (v1 universe) |
| `pipeline/fetch_bulk.py` | yes | SEC bulk zips → per-ticker files for the wide universe |
| `pipeline/fundamentals.py` | yes | XBRL parsing, point-in-time accessors |
| `pipeline/features.py` | yes | v1 panel (S&P members) and shared feature code |
| `pipeline/features_v2.py` | yes | Wide top-1000 panel |
| `pipeline/model.py` | yes | v1 logistic models (the price-only model is still used) |
| `pipeline/model_v2.py` | yes | G1 v2 composite (A) and ridge (B) walk-forward evaluation |
| `pipeline/style.py`, `style_test.py`, `lean_test.py` | yes | Buffett & Munger and Magic 15 scores and their tests |
| `pipeline/build_site.py` | yes | Scores the current universe and writes `build/data/main.json` and `otw.json` |
| `pipeline/render.py` | yes | Template + CSS + JS + data → `build/clear/index.html`, `build/clear/otw/index.html` |
| `web/template.html`, `web/app.js`, `web/style.css` | yes | Dashboard |
| `scripts/encrypt-pages.sh` | yes | StatiCrypt encryption + leak check |
| `scripts/rebuild.sh` | yes | Full manual rebuild, in order |
| `scripts/verify_live.py` | yes | Post-deploy check: password shell only, unlock works |
| `docs/PREREGISTRATION*.md` | yes | Rules written before each test, plus results |
| `.staticrypt.json` | yes | StatiCrypt salt (not secret; keeps the "remember me" storage stable) |
| `index.html`, `otw/index.html` | yes | **Encrypted** published pages |
| `cache/`, `build/`, `*.csv`, `*.parquet`, `.venv/` | **no** (`.gitignore`) | All data, holdings, predictions and cleartext pages |

Box locations outside the repo:

- `/workspace/g1-bulk/`: SEC bulk zips (~3 GB), `company_tickers_exchange.json`, `wide_cik.json`, `wide_need.txt`.
- `/workspace/g1-cache/`: the Danelfin client and its cache and log (Section 2). Never published.
- `/workspace/uploads/nov8/{OTW,OTW2,SWB,Jette,NEW}_holdings.csv`: Danelfin portfolio exports. Never published. The folder can be changed with the `G1_HOLDINGS_DIR` environment variable.

---

## 2. Danelfin access

### What Danelfin is used for

1. **AI Score shown on the page.** It comes from Gary's Danelfin portfolio CSV exports (Nov 8), **not** from the API. `common.load_books()` reads the five CSVs and `build_site.py` takes these columns:
   - `Ticker`
   - `Company`
   - `AI Score` (1–10)
   - `Shares` (shown only for the NEW book)

   The exports also contain `Fundamental`, `Technical`, `Sentiment`, `Low Risk`, `Rank`, `Sector`, `Industry`, `Price` and other columns, which G1 does not use. **The page makes no Danelfin calls.**
2. **A one-off research comparison** (Nov 9, 2026). It used historical top-100 snapshots from the API (see "Studies" below).
3. **Optional on-demand pulls** for names Gary picks. These use the same budgeted client.

### API facts (as observed)

- **Plan:** the free plan includes **500 calls per month**. Gary's rule is **zero extra cost**: stay inside the free allowance, never change the plan, never enter payment details. If a response mentions a quota, overage, rate limit or upgrade, **stop calling immediately**.
- **Key:** stored at `/home/box/agent-data/secrets/danelfin-api-key` (box secrets, outside the repo). Read it only from that file, inside the process. Never print, log, commit or return it.
- **Login:** the API needs only the key. No G1 code uses the Danelfin website login. Any saved website login in Gary's vault is not needed to call the API, and no vault item ID is recorded in the repo or the G1 files.
- **Base URL:** `https://apirest.danelfin.com`.
- **Endpoint used:** `GET /ranking`.
- **Auth:** HTTP header `x-api-key: <key>`.

**Request shapes tried:**

| Params | Result | Response shape |
|---|---|---|
| `ticker=AAPL` | 200 | About the last 100 days of daily scores for one ticker. Format: `{"YYYY-MM-DD": {"aiscore", "fundamental", "technical", "sentiment", "low_risk"}, …}`. The AAPL test returned 100 dates, 2026-06-18 → 2026-11-07. |
| `date=YYYY-MM-DD` | 200 | That day's **top 100** only. Format: `{"date": {"TICKER": {"aiscore", "sentiment", "technical", "fundamental", "low_risk"}, …}}` |
| `date=…&sector=financials` | 200 | Top names within that sector on that date |
| `date=…&ticker=AAPL,MSFT,JPM` (multi-ticker) | **404** | Not supported |

- **Call count:** 40 calls have been used in total (1 ticker, 1 multi-ticker 404, 1 sector, 37 quarterly top-100 snapshots). **About 460 calls remain this month.** No quota, overage or upgrade messages were seen.

### The budgeted client: `/workspace/g1-cache/dfn.py`

- `call(path, params)` builds a cache file name from the path and sorted params, for example `ranking__date-2017-03-31.json` or `ranking__ticker-AAPL.json`. It stores files in `/workspace/g1-cache/danelfin/`.
- **Cache first.** If the file exists, it is returned and no network call is made. Cached responses never expire. To refresh a ticker, delete or rename its cache file.
- **Budget guard.** `BUDGET = 150`. Before any network call it counts the lines in `danelfin/calls.log`. That count is cumulative across all phases, not monthly. If the count is ≥ BUDGET, it exits with "budget exhausted". Per-task caps from Gary (for example "at most 80 calls" or "0 calls") are stricter and must be respected separately.
- **Key handling.** The key is read from the secrets file just before the request and deleted from memory right after.
- **Logging.** Every network call appends one line to `calls.log`: timestamp, path, params JSON, HTTP status and response bytes. The key is never logged.
- **Errors.** A 200 response is cached raw. Anything else returns `{"_status", "_body"}` and is not cached.
- **Command line.** `python dfn.py /ranking ticker=XYZ` prints whether the result came from cache or network, the calls used so far, and a short sample.
- **Batch fetches.** `fetch_top100.py` shows the pattern: one quarter-end date per call, a 7-second sleep between network calls, and a stop on any non-200 response or on "quota", "overage", "upgrade", "limit exceeded" or "rate limit" in the body.

**On-demand pulls for picked names.** Gary's standing guidance: pull API data only for his ~70 portfolio names and for names he picks from recommendations. To do it:

1. Confirm the remaining budget: `wc -l /workspace/g1-cache/danelfin/calls.log`, compared against the 500/month plan and any per-task cap.
2. Run `python /workspace/g1-cache/dfn.py /ranking ticker=XYZ`.
3. Read `danelfin/ranking__ticker-XYZ.json`. The latest date's `aiscore` is the current score.

The dashboard does not read these files today. To show an API-pulled score, add it to the book rows in `build_site.py`, which currently takes `AI Score` from the CSV.

### Studies (local only, never published)

- **`/workspace/g1-cache/h2h.py`** compared Danelfin with G1 using 37 quarter-end top-100 snapshots (2017-03-31 → 2026-03-31). Results are in `h2h_results.json`.
  - **Study 1:** the top-100 basket's forward excess return vs SPY.
  - **Study 2:** among S&P members, a "was in Danelfin's top 100" flag vs G1, and a stacked model.
- **Result:** the Danelfin flag's rank IC was not significant at any horizon (best t ≈ 1.7 at 6m). The top-100 basket lagged SPY from 12m onward (−18% at 60m, t −3.3).

---

## 3. Price data

### Offline (pipeline): `pipeline/fetch_prices.py`

- **URL:** `https://query1.finance.yahoo.com/v8/finance/chart/{SYM}?period1=946684800&period2={now}&interval=1d&events=div%2Csplit&includeAdjustedClose=true`
  - `SYM` is the ticker with `.` replaced by `-` (`BRK.B` → `BRK-B`).
  - Use `period1`/`period2`. `range=max` only returns 3-month bars.
- **Header:** `User-Agent: Mozilla/5.0`. A full Chrome User-Agent string got HTTP 429.
- **Retries:** 6 threads, up to 4 attempts. On a 429 it sleeps 5s, 10s, … A 404 marks the ticker as not on Yahoo (about 220 historical S&P tickers).
- **Output:** `cache/prices/{T}.parquet` with columns `close`, `adj` (adjusted close), `vol` and `split` (split ratio on split days, else 1).
- **Caching:** existing files are skipped unless `--force` is passed.
- **SPY** is the benchmark.
- **10-year Treasury:** `^TNX` daily close (percent) is fetched by `fetch_universe.py` into `cache/tnx.parquet`.

### In the browser (`web/app.js`)

- **Chart URL:** `https://{query1|query2}.finance.yahoo.com/v8/finance/chart/{SYM}?range=5y&interval=1wk&includeAdjustedClose=true` (weekly bars).
- **Fetch order** for each symbol (`fetchChart`). The first that returns a valid `chart.result[0]` wins:
  1. Direct `query1` (usually blocked by CORS on GitHub Pages). 8s timeout.
  2. `https://api.allorigins.win/raw?url=<query2 URL>`. 25s timeout.
  3. `https://api.allorigins.win/get?url=<query2 URL>` (JSON wrapper; the body is parsed from `.contents`). 25s.
  4. `…/raw?url=<query1 URL>`. 25s.
  5. `…/get?url=<query1 URL>`. 25s.
- **SPY:** two attempts. If both fail, it falls back to the **bundled SPY weekly series**, `meta.spy_w`: the last 262 weekly closes, keyed by the Monday of each week, written at build time. The status line then notes "SPY from bundled history; beta slightly stale".
- **Refresh button:** re-scores every ticker in the current tab.
  - Six parallel workers, one retry per ticker.
  - Failed tickers keep their shipped score and are listed.
  - Lists over 60 names show a "this can take 10+ minutes" warning.
- **Live price features** (`priceFeatures`) use the same definitions as Python, on weekly adjusted closes:
  - `mom_12_1` = P[t−4]/P[t−52] − 1
  - `mom_6_1` = P[t−4]/P[t−26] − 1
  - `mom_3` = P[t]/P[t−13] − 1
  - `rev_1m` = P[t]/P[t−4] − 1
  - `mom_36_12` = P[t−52]/P[t−156] − 1
  - `dd_52w` = P/max(52w) − 1, with at least 40 weeks
  - `trend40` = P/mean(40w) − 1, with at least 30 weeks
  - `vol_1y` = sd(52 weekly log returns) × √52, with at least 40 weeks
  - `beta_2y` = cov/var of weekly log returns vs SPY over 104 weeks, with at least 52 pairs
  - `mdd_3y` = worst peak-to-trough drop in 156 weeks, with at least 100 weeks
- **Live valuation** (`fundFeatures`) uses the bundled raw fundamentals (`rev`, `ebit`, `cfo`, `capex`, `equity`, `debt`, `cash`, `shares_adj`) and the live price:
  - mcap = price × shares; EV = mcap + debt − cash
  - `ey` = EBIT/EV
  - `fcfy` = (CFO − capex)/mcap
  - `sy` = revenue/EV
  - `bm` = equity/mcap
  - `ey_vs_hist` / `fcfy_vs_hist` = value minus the bundled 60-month median
- **Look up (ticker search):**
  - Input is uppercased and stripped to `[A-Z0-9.-]`, then fetched live.
  - Tickers with bundled SEC fundamentals (`kind="full"`) get the full score and the style boxes.
  - Any other ticker (ETFs, foreign or untracked names) gets the **price-only model**, and its style boxes show "—".
- **Research list:** "Pin to Research" saves `{t, name, s, kind, px, sty, at}` in `localStorage` under the key **`g1.research.v1`**.
  - It is per browser, never sent anywhere.
  - Refresh updates pinned entries.
  - Bundled style scores take precedence over the stored ones.

---

## 4. Fundamentals (SEC EDGAR)

- **User-Agent:** every SEC request must carry a descriptive User-Agent with a contact address. G1 uses `G1-invest research airbot@mail.grokbot.com`. A noreply address got HTTP 403. `fetch_edgar.py` throttles to 1 request per 0.13s and retries 429/503 after 10s.
- **Endpoints:**
  - Ticker → CIK: `https://www.sec.gov/files/company_tickers.json`. Wide candidates: `https://www.sec.gov/files/company_tickers_exchange.json` (fields `cik, name, ticker, exchange`).
  - Per company: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (XBRL facts) and `https://data.sec.gov/submissions/CIK##########.json`. Only `cik, name, sic, sicDescription, tickers, exchanges, fiscalYearEnd, category` are kept.
  - Bulk (wide universe): `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip` (~1.4 GB) and `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` (~1.6 GB). They hold one `CIK##########.json` per company, extracted to `cache/edgar/{T}.facts.json` / `{T}.sub.json`.

### Tags → raw items (`fundamentals.py`)

Earlier names in each list win. IFRS names are a fallback for foreign filers.

| Item | XBRL concepts |
|---|---|
| rev (flow) | Revenues, RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet, RevenueFromContractWithCustomerIncludingAssessedTax, SalesRevenueGoodsNet, RevenuesNetOfInterestExpense, ifrs:Revenue |
| gp | GrossProfit, ifrs:GrossProfit |
| ebit | OperatingIncomeLoss, ifrs:ProfitLossFromOperatingActivities |
| ni | NetIncomeLoss, ProfitLoss, NetIncomeLossAvailableToCommonStockholdersBasic, ifrs:ProfitLossAttributableToOwnersOfParent, ifrs:ProfitLoss |
| cfo | NetCashProvidedByUsedInOperatingActivities, …ContinuingOperations, ifrs:CashFlowsFromUsedInOperatingActivities |
| capex | PaymentsToAcquirePropertyPlantAndEquipment, PaymentsToAcquireProductiveAssets, ifrs:PurchaseOfPropertyPlantAndEquipment… |
| intexp | InterestExpense, InterestExpenseNonoperating, InterestExpenseDebt, InterestAndDebtExpense, ifrs:FinanceCosts, ifrs:InterestExpense |
| assets (instant) | Assets, ifrs:Assets |
| equity | StockholdersEquity, …IncludingPortionAttributableToNoncontrollingInterest, ifrs:EquityAttributableToOwnersOfParent, ifrs:Equity |
| cash | CashAndCashEquivalentsAtCarryingValue, CashCashEquivalentsRestrictedCash…, Cash, ifrs:CashAndCashEquivalents |
| ltdebt | LongTermDebt, LongTermDebtNoncurrent, LongTermDebtAndCapitalLeaseObligations, ifrs:NoncurrentPortionOfNoncurrentBorrowings, ifrs:Borrowings |
| stdebt | LongTermDebtCurrent, DebtCurrent, ShortTermBorrowings, ifrs:CurrentBorrowings, ifrs:CurrentPortionOfNoncurrentBorrowings |
| shares | WeightedAverageNumberOfDilutedSharesOutstanding first; then dei:EntityCommonStockSharesOutstanding, CommonStockSharesOutstanding; then implied = \|quarterly NI / quarterly diluted EPS\| |

**Flows to quarterly and TTM:**
- Direct 3-month facts (80–100 days) are used as is.
- Missing quarters come from differences between consecutive year-to-date facts that share a start date.
- Annual facts (350–380 days) are kept too.
- TTM is the sum of 4 consecutive quarters spanning 255–290 days between their period ends, or an annual fact.

**Shares:**
- Shares are split-adjusted using Yahoo split events after the filing's period end.
- Diluted shares are preferred while they are current. A later-priority series is used only for periods more than 200 days after the preferred series ends.
- `BRK.B` cover-page shares are multiplied by 1,500 (Class-A equivalents).

**Point-in-time rule:**
- Only the **first-filed** value for each period is used, so restatements are ignored.
- A value becomes usable **2 days after its filing date** (`LAG_DAYS = 2`).
- At date t, the accessor returns the latest period available by t.
- Values whose period ended more than **550 days** before t are treated as missing (`STALE_DAYS = 550`).
- Fundamentals start at 2009-06-30.

**Derived features** (`features.fund_features`):
- Market and enterprise value:
  - mcap = close × split-adjusted shares
  - debt = ltdebt + stdebt
  - EV = mcap + debt − cash
- Valuation:
  - `ey` = EBIT/EV
  - `fcfy` = (CFO − capex)/mcap
  - `sy` = rev/EV
  - `bm` = equity/mcap
- Returns and margins:
  - `roe` = NI/equity (equity > 0)
  - `roic` = EBIT/(equity + debt − cash)
  - `gm` = GP/rev
  - `om` = EBIT/rev
- Growth:
  - `rev_g1`: 1-year revenue growth
  - `rev_g3`: 3-year revenue CAGR
  - `rev_accel`: growth now minus growth a quarter ago
- Margin quality, from 12 quarterly operating margins (needs at least 6):
  - `om_stab` = −sd of operating margin
  - `om_trend` = operating margin now minus 4 quarters ago
- Earnings surprise:
  - `sue`: year-over-year change in quarterly net income ÷ sd of the previous 8 such changes, clipped to ±10
- Balance sheet:
  - `lev` = debt/assets
  - `intcov` = log1p(clip(EBIT/interest, −1, 1000))
- Dilution:
  - `dil_1y` / `dil_3y`: share-count change over 1 and 3 years
- Earnings quality and profitability:
  - `accruals` = (NI − CFO)/assets
  - `gpa` = GP/assets
  - `roa` = NI/assets
- Own-history comparison:
  - `ey_vs_hist` / `fcfy_vs_hist`: value minus the stock's own trailing 60-month median (at least 24 months)
- Missing data:
  - Missing items give NaN.
  - Features that need missing inputs stay NaN and are treated as **neutral** when scored (rank 0 or percentile 0.5; see Section 6).
  - Banks and insurers often lack EBIT or gross profit.

**Sector:**
- `sic_sector()` maps the SEC SIC code to 12 buckets (Tech, Health, Financials, …).
- GICS sectors from Wikipedia are shown only as labels.

**Known gaps:**
- Names with no usable XBRL fundamentals are scored with the price-only model. These are ETFs, multi-class filers that report shares only by class, and companies whose current SEC entity has too little history.

---

## 5. Universe construction (`fetch_universe.py`, `features_v2.py`)

- **Historical S&P 500 membership:** GitHub `fja05680/sp500`, file **"S&P 500 Historical Components & Changes (Updated).csv"**. Columns are `date,tickers`, covering 1996-01-02 → 2026-08-18. Membership at date t is the last row on or before t.
- **Current S&P 500:** the Wikipedia "List of S&P 500 companies" table `id="constituents"` (Symbol, Security, GICS Sector, CIK). It is parsed with the standard library and written to `cache/sp500_current.json`.
- **v1 universe** (`cache/universe_all.txt`) = everyone who was an S&P member since 2008-01-01, plus current members, book tickers and SPY.
- **Wide v2 universe:**
  - Candidates are every ticker in SEC `company_tickers_exchange.json` on NYSE, Nasdaq or CBOE, first ticker per CIK (6,054 tickers), plus `universe_all.txt`.
  - A ticker is kept if it has both Yahoo prices and SEC facts (5,887 tickers).
  - The panel covers month-ends from 2010-01 plus the latest trading day.
  - At each date, `univ` = price ≥ $5, known market cap > 0, and **top 1,000 by market cap**.
  - Coverage: about 970 names per date on average. There were 217 in Jan 2010 and 656 in Jan 2011 (short price history), and 1,000 from 2012 on.
- **Survivorship caveats:**
  - Non-S&P names that delisted or were acquired before today are **missing**, because only today's SEC ticker list is free.
  - Historical S&P names are kept when Yahoo still has their prices. Yahoo coverage of S&P members is about 52% in 2005, 73% in 2015 and 97% in 2025.
  - If a stock stops trading mid-horizon, its proceeds are assumed to sit in SPY from its last price.
  - These gaps flatter backtests somewhat. The page says so.

---

## 6. Scores and formulas

### Labels

- y_h = (1 + r_stock)/(1 + r_SPY) − 1 over h months on adjusted closes, from month-end t to t + h. A stock "beats SPY" when y_h > 0.
- Horizons: 6, 12, 24, 36, 48 and 60 months.

### G1 v2 composite ("A"): the live score for names with fundamentals

- Every input is converted to a **within-sector percentile rank** at each date, minus 0.5. Missing inputs count as 0.
- Four equal-weight pillars, each the mean of its signed components:
  - **Quality** = mean(+gpa, +roa, −accruals)
  - **Value** = mean(+fcfy, +ey, +ey_vs_hist)
  - **Low dilution** = −dil_1y
  - **Balance sheet** = mean(−lev, +intcov)
- **A = mean of the four pillars.** Nothing is fitted.
- On the page, `build_site.py` ships per-sector 101-point quantile tables (`meta.sq`) for each input, taken from the current top-1000 universe. A sector needs at least 5 values for a feature, otherwise that feature reads neutral.
- Both Python and JS use `qpct()`: ties take the midpoint, and gaps between quantiles are interpolated linearly. The two produce identical scores (max difference about 1e-16).

### P(beat SPY) and the excess-return band

- A's percentile among the current top-1000 (`pq`, 101 quantiles of A) is mapped by linear interpolation onto a **decile table** with midpoints 0.05 … 0.95.
- The decile table comes from the v2 out-of-sample rows (wide universe), with deciles taken per date. For each decile:
  - `hit` = share with y > 0. This is "Chance to beat S&P 500".
  - `p10`, `p50`, `p90` of y. These are the "bad case / typical / good case" band.
- **"Usual"** is that horizon's base rate. On the page, "above usual" or "below usual" means at least 3 percentage points above or below it.

### Price-only fallback (v1 logistic model; REPLACED in v4 by S_price, see section 0)

- Features: the 10 price features, as per-date percentile ranks among S&P members, minus 0.5 (missing = 0).
- One L2 logistic regression per horizon (C = 0.5), trained from 2003 and walk-forward.
- The logit p is converted to a percentile among current S&P members and mapped to v1's out-of-sample decile table. That table is restricted to dates from v1's full-model test start, so its base rate is comparable.
- Out of sample it has no edge at any horizon (rank IC −0.034 to +0.038). It is only a fallback.

### Agree / Disagree with Danelfin (per horizon)

- G1's direction: score percentile `pct` ≥ 0.80 is bullish; ≤ 0.20 is bearish; anything else has no view.
- Danelfin's direction: AI Score ≥ 7 is bullish; ≤ 4 is bearish; anything else has no view.
- **Agree** = both have a view and it is the same. **Disagree** = both have a view and they are opposite. **Neutral** = anything else. **"—"** = no Danelfin score (names outside the books).
- The pills are green, red and grey. In the details view each horizon also gets a dot.

### Buffett & Munger (0–10, absolute rules; `style.bm_components`)

- A missing input scores **half** that rule's points.
- History stats use the ticker's own monthly panel rows over the last 60 months (at least 24 rows).

| Rule | Points |
|---|---|
| Durable ROE: 5y median ROE ≥ 15% **and** 5y min ROE ≥ 10% → 2; else 5y median ≥ 12% → 1; else 0 | 2 |
| Low leverage: debt/assets ≤ 0.30 | 1 |
| Stable margins: `om_stab` ≥ −0.03 | 1 |
| Consistent profits: 5y min ROA > 0 | 1 |
| Gross-margin moat: gm ≥ 40% → 2; ≥ 25% → 1 | 2 |
| No net dilution: 3y share change ≤ 0 | 1 |
| Owner-earnings yield: FCF/mcap ≥ 10y Treasury → 2; ≥ 0.6 × Treasury → 1 | 2 |

- On the page, the six price-free rules are computed at build time.
- The FCF rule is recomputed live on Refresh, using the live price and the Treasury yield from build time (`meta.tsy`; 4.86% at the last build).

### Magic 15, lean version (live since 2026-11-11)

- **Magic 15 = 10 × mean(Quality compounders, Downside protection).**
- Each pillar is the mean of percentile ranks (0–1) across the current top-1000 universe (**not** within sector). A missing input counts as 0.5. A "−" sign means 1 − percentile.
  - **Quality compounders** (Ackman, Combs, Weschler): +roic, +gpa, +om_stab, −dil_3y
  - **Downside protection** (Marks, Karsh): −lev, +intcov, +mdd_3y (shallower is better), −vol_1y
- The page ships 101-point quantiles of these inputs (`meta.mq`) and recomputes them on Refresh.
- **Deliberately left out** (the hover text says so): deep value (Klarman, Pabrai), durable growth (Thiel, Botha, Lin, Fenton, Cohler), macro trend (Druckenmiller) and yield/credit value (Black, Rowan). In the six-pillar test they cancelled each other out or added little.
- The display name is the `"name"` field of `meta.magic` in `build_site.py`.

Both style scores are **rule-based proxies of published principles, not those investors' actual views**. They are display-only and never change P(beat SPY).

---

## 7. Backtest method and results

### Method

- **Walk-forward with yearly retraining.**
  - The fitted models (v1 logistic, v2 ridge B) are trained for test year Y only on rows whose label window ended before Jan 1 of Y (date + h < Y-01-01).
  - Each fit needs at least 36 training dates.
  - Test years start in 2014.
- **Fixed-rule scores** (A, Buffett & Munger, Magic 15) need no training. They are scored on the same month-end dates from 2014, wherever the label is known.
- **Metrics:**
  - **AUC:** pooled, for "beats SPY".
  - **Rank IC:** the mean per-date Spearman correlation between score and y.
  - **Overlap-adjusted t** = mean(IC)/sd(IC) × √(n_dates / h). Monthly dates with h-month windows overlap heavily.
  - **Top-minus-bottom decile:** mean y of the top 10% minus the bottom 10%, averaged over dates.
  - **ECE:** mean |predicted − realized| across the 10 calibration bins, weighted.
  - Per-year IC.
- **Redundancy checks:**
  - Per-date Spearman correlation with A.
  - **Partial IC:** the score's rank is residualized on A's rank per date by OLS, then the residual's IC is measured.
  - The 50/50 rank blend with A minus A alone, with an overlap-adjusted t.
- **Pre-registration:** rules and decision thresholds are written in `docs/PREREGISTRATION*.md` and committed **before** each test. Results and deviations are appended afterward. Weights are never tuned on the results.
  - `PREREGISTRATION.md` (G1 v2) was committed at `384180f`.
  - `PREREGISTRATION_STYLE_SCORES.md` at `0a10513`.
  - `PREREGISTRATION_LEAN_MAGIC15.md` at `f66fe64`.

### Decision rules (abridged)

- **G1 v2:** redeploy if rank IC t > 2 at one or more horizons (S&P or wide) **and** no horizon is more than 0.03 below v1's IC. **Passed** with composite A. Ridge B did not.
- **Style scores:** KEEP if t > 2 somewhere **and** partial IC vs A > 0 with t > 1.5 at two or more horizons. SIMPLIFY if dropping one pillar raises IC at four or more horizons, or a single pillar has t > 2 at two or more. Otherwise DROP. Result: Buffett & Munger **KEEP**; the six-pillar Magic 15 **SIMPLIFY**.
- **Lean Magic 15:** SWAP if t > 2 somewhere, **and** IC is no more than 0.01 below the old Magic 15's at four or more horizons, **and** partial t > 1.5 at two or more. **Passed (swapped).**

### Key results (wide top-1000, rank IC with t in brackets, month-ends 2014+)

| Horizon | G1 composite A | Buffett & Munger | Lean Magic 15 | Old 6-pillar Magic 15 | G1 v1 (S&P, retired) |
|---|---|---|---|---|---|
| 6m | .036 (2.4) | .053 (3.1) | .048 (2.2) | .041 (1.9) | −.014 (−0.8) |
| 12m | .049 (2.2) | .070 (2.9) | .068 (2.5) | .047 (1.7) | .004 (0.1) |
| 24m | .076 (2.2) | .096 (2.8) | .106 (2.9) | .068 (2.1) | .057 (1.5) |
| 36m | .090 (2.4) | .117 (4.2) | .130 (3.4) | .100 (2.7) | −.031 (−0.5) |
| 48m | .104 (2.6) | .137 (3.7) | .144 (3.5) | .121 (2.7) | −.108 (−1.7) |
| 60m | .108 (2.8) | .135 (3.4) | .142 (3.0) | .107 (2.1) | −.099 (−2.5) |

- **Scope of the columns:** A's numbers here use all month-ends from 2014. The v2 evaluation used its own walk-forward test windows: 6m 0.036 (2.41), 12m 0.047 (2.01), 60m 0.156 (3.06). The v1 column is on S&P members only.
- **S&P-only results are weaker.** A has t of about 1–2 across horizons.
- **Value beyond G1 (partial IC t):** Buffett & Munger 1.5–2.4; lean Magic 15 1.4–1.9.
- **Timing:** much of the edge came in 2020–2022, and some years are negative (for example 2024 at short horizons).
- **Long horizons are thin:** 48–60m rest on about 1–2 independent periods.
- **Overall verdict:** a modest, real-looking edge. Not a trading signal.

---

## 8. Dashboard build and publishing (v2/v3-era description; for v4 files, config and scripts see section 0)

1. `build_site.py` writes `build/data/main.json` (all tabs) and `build/data/otw.json` (OTW and OTW #2 tickers only). Both are gitignored. Contents:
   - `meta`: build time, price date, the quantile tables `sq` and `mq`, Treasury yield, Magic 15 definition, backtest summaries, bundled SPY weekly series.
   - `models`: decile tables and metrics. For the price-only model, also coefficients and quantiles.
   - `tick`: per-ticker inputs, raw fundamentals and shipped scores.
   - `books`: ticker, name, AI Score and, for NEW only, shares.
2. `render.py` substitutes `__CSS__`, `__JS__` and `__DATA__` (with `</` escaped) into `web/template.html`. The data goes into `<script id="g1data" type="application/json">`. Output: `build/clear/index.html` (page `main`) and `build/clear/otw/index.html` (page `otw`). Titles are "G1 · Gary A" and "G1 · OTW · Gary A".
3. `scripts/encrypt-pages.sh`:
   - Reads the password from the file at `$G1_DASHBOARD_PASSWORD_FILE`. The default is `/home/box/agent-data/secrets/danelfin-dashboard-password`, read via `tr -d '\r\n' < file`.
   - Exports it only as `STATICRYPT_PASSWORD` for the command, then unsets it. It is never echoed or written to disk.
   - Runs: `npx --yes staticrypt <clear.html> -d <tmp> -c .staticrypt.json --remember 14 --short --template-title "Gary A · G1" --template-color-primary "#3b82f6" --template-color-secondary "#0f172a" --template-instructions … --template-button "Unlock" --template-placeholder "Password" --template-remember "Remember for 14 days"` (StatiCrypt 3.5.4, Node 24).
   - Copies the outputs to `index.html` and `otw/index.html`.
   - **Leak check:** fails if either file matches `g1data|"tick":|"models":|OTW_holdings`.
4. Commit only `index.html`, `otw/index.html` and code or docs. Commit author: `dot2dot123 <dot2dot123@users.noreply.github.com>`. Push to `main`. GitHub Pages serves the repo root of `main`; `.nojekyll` is present. Pages updates about 1 minute after the push.
5. Run `.venv/bin/python scripts/verify_live.py`. It confirms:
   - Both URLs contain no leak pattern. Extra private patterns, such as the owner's full name, can be passed in `G1_LEAK_EXTRA` so they never appear in the repo.
   - The table is absent before unlock.
   - Unlocking with the password file works and renders rows.
   - There are no page errors.
   - It prints PASS or FAIL. The password is never printed.

Last deploy check: PASS, with 502 rows on the main page and 25 on the OTW page. Score parity between Python and JS was also checked (max difference about 1e-15).

---

## 9. Biweekly "top 10" email routine

> **What the code can confirm:** this repo and the G1 files on the box contain **no scheduler, workflow or email code**. The routine, if it is running, lives in the bot's own routine system, which this guide cannot inspect. What follows is the approved design. Check it against the routine's actual settings before relying on it.

- **Approved by Gary:** one routine, an exception to the "no routines" default.
  - **When:** the 1st and 15th of each month, at about 8:00 AM PT.
  - **What:** a G1 "top 10 recommendations" email covering his portfolios.
  - **Sent to:** Gary's own email address, from the bot's inbox.
  - **Delivery:** prepared as a **draft card for his approval**, not sent automatically.
- **Intended steps each run:**
  1. Read the latest G1 scores (shipped page data or a fresh `build_site.py` run).
  2. Rank the book names (and any candidates) by chance to beat the S&P at the chosen horizons.
  3. Show the Danelfin agreement and the Buffett & Munger and Magic 15 scores.
  4. Draft the top 10 with one-line reasons and the "personal use only, not financial advice" line.
- **Danelfin budget:** pull API data only for the ~70 portfolio names and for names Gary picks from the recommendations, using `dfn.py` (cache first, logged, within 500 calls/month, stop on any quota or upgrade text). One ticker call per name per run would use about 140 calls a month for 70 names, inside the free plan. Re-using cached results costs nothing.

---

## 10. Rebuild-from-scratch checklist

**Prerequisites**
- Linux box with Python 3.13, Node 24 (for `npx staticrypt`), git, and Google Chrome (`/usr/bin/google-chrome`, only for `verify_live.py`).
- About 15 GB free disk: SEC bulk zips about 3 GB, extracted `cache/edgar` about 10 GB.
- RAM: the build ran on a 15 GB box. `features_v2.py` uses 7 processes.
- GitHub CLI logged in as `dot2dot123`.
- Secrets (paths only):
  - `/home/box/agent-data/secrets/danelfin-dashboard-password` (StatiCrypt password)
  - `/home/box/agent-data/secrets/danelfin-api-key` (only for optional Danelfin pulls)
- Danelfin portfolio exports at `/workspace/uploads/nov8/{OTW,OTW2,SWB,Jette,NEW}_holdings.csv`, or set `G1_HOLDINGS_DIR`.

**Steps**
1. `git clone https://github.com/dot2dot123/g1-invest && cd g1-invest`
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (numpy, pandas, pyarrow, scikit-learn, scipy, requests; playwright is optional).
3. `bash scripts/rebuild.sh`. It runs, in order:
   1. `fetch_universe.py`
   2. `fetch_prices.py` (v1 universe with `--force`, then wide names not yet cached)
   3. `fetch_edgar.py`
   4. `fetch_bulk.py --force`. Skip it with `SKIP_BULK=1` if the bulk data is already extracted.
   5. `features.py`
   6. `model.py 6,12,24,36,48,60`
   7. `features_v2.py`
   8. `model_v2.py`
   9. `style_test.py`
   10. `lean_test.py`
   11. `build_site.py`
   12. `render.py`
   13. `encrypt-pages.sh`

   A full first run takes hours. Most of the time goes to Yahoo price downloads for about 6,000 tickers and the 3 GB SEC download.
4. Review the console output (backtest tables, verdicts) and spot-check `build/clear/index.html` locally (`python -m http.server` in `build/clear`).
5. `git add index.html otw/index.html` (plus any code or docs), commit as dot2dot123, `git push origin main`.
6. Wait about 1 minute, then run `.venv/bin/python scripts/verify_live.py`. It must print PASS.
7. Changing a model or score? Write and commit the rules in `docs/PREREGISTRATION_*.md` **before** testing. Append the results afterward. Deploy only if the written rule passes.

**Rules (do not break)**
- Free data only: Yahoo, SEC, Wikipedia, GitHub `fja05680`, AllOrigins. No paid data.
- Danelfin: zero extra cost. Stay within the free 500 calls/month and any per-task cap (often 0), cache first, and stop on any quota, overage, rate-limit or upgrade message. Never change the plan or enter payment details.
- Never print, log, commit or return the password, the API key, plaintext holdings or prediction JSON. `cache/`, `build/`, `*.csv` and `*.parquet` stay gitignored. The leak check must pass.
- Public display name is **"Gary A"**, never the full name.
- Every page says **"Personal use only, not financial advice"**, and that the style scores are rule-based proxies, not those investors' views.
- No GitHub Actions workflows, cron or polling for the dashboard. Refresh happens in the browser, on demand.
- Do not modify the separate `danelfin-portfolio-dashboard` repo.
