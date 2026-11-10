# G1 v2 — pre-registration

Written **2026-11-10 (America/Los_Angeles), before any v2 test was run.** Committed to git before any v2 test was run; the commit timestamp is the record. Nothing below may be changed after seeing v2 results. Any deviation must be listed in a "Deviations" section appended later, with the reason.

## Data (free only)
* Prices: Yahoo chart API (daily adjusted close, split events).
* Fundamentals: SEC EDGAR companyfacts (XBRL), first-filed value per period, usable 2 days after filing, values older than 550 days treated as missing (same as v1).
* Sector: SEC SIC code mapped to 11 coarse sectors (same mapping as v1, `pipeline/features.py:sic_sector`).

## Universe (point-in-time)
* Candidates: every SEC registrant with a ticker in SEC `company_tickers_exchange.json` listed on NYSE, Nasdaq or CBOE, plus every historical S&P 500 member since 2008 (including delisted names when Yahoo still has prices), plus the five book tickers.
* At each month-end t (2010-06 onward): keep names with a Yahoo price at t, price ≥ $5, a market cap computable from point-in-time XBRL shares, and rank in the **top 1,000 by market cap** at t ("Russell-1000-like").
* Residual survivorship bias is expected (non-S&P names that delisted before today are mostly missing from both SEC's current ticker list and Yahoo) and will be reported.

## Targets
* `y_h` = (1 + stock total return) / (1 + SPY total return) − 1 over h ∈ {6, 12, 24, 36, 48, 60} months (proceeds into SPY if the stock stops trading).
* Rank target for the learned model: per-date cross-sectional percentile of `y_h` within the universe, minus 0.5.

## Model A — pre-registered composite (no fitting, identical for all horizons)
All inputs ranked **within sector** per date (percentile − 0.5; missing → 0). Sign shown in brackets.
* Quality = mean( gross profit / assets [+], net income / assets [+], accruals (NI − CFO) / assets [−] )
* Value = mean( FCF / market cap [+], EBIT / EV [+] (within-sector rank, i.e. vs sector), EBIT/EV minus own trailing-60-month median [+] )
* Low dilution = 1-year diluted share-count change [−]
* Balance sheet = mean( debt / assets [−], log interest coverage [+] )
* **Score = (Quality + Value + Low dilution + Balance sheet) / 4.** Equal, fixed weights.

## Model B — reworked learned model (one per horizon)
* Features: v1 long-horizon fundamental set + price features (momentum 12-1, 6-1, 3m, 1m reversal, 52w-high distance, 40w trend, volatility, beta, 36-12 momentum, 3y max drawdown) + gross profit/assets + ROA, all ranked **within sector** per date.
* Ridge regression (alpha = 100, standardized inputs as given) on the rank target. Walk-forward, yearly retrain, expanding window, purged: training rows need t + h < 1 January of the test year.

## Probability / calibration (both models)
* P(beat SPY) = hit rate of the score's per-date decile, estimated only from training-period rows (walk-forward).

## Evaluation (unchanged from v1 where possible)
* Out-of-sample test years 2014 onward (or first year with ≥ 36 training months for B; A is scored from 2011 onward but compared over the same test dates as B).
* Metrics per horizon: pooled AUC (score vs beat-SPY), mean per-date Spearman rank IC with overlap-adjusted t (mean/sd × √(dates / h)), top-minus-bottom decile mean excess vs SPY, ECE of the decile-calibrated probability.
* Reported on (1) the wide top-1,000 universe and (2) the S&P 500 member subset (comparable with v1), plus the S&P subset at the 37 Danelfin quarter-end dates (comparable with the Danelfin top-100 substitute test).

## Decision rule for redeploying the dashboard
Redeploy v2 only if, on the S&P 500 subset or the wide universe, a v2 model (A or B) has rank IC overlap-adjusted **t > 2 at one or more horizons** AND at no horizon its rank IC is more than 0.03 below v1's. Otherwise the dashboard stays on v1 and results are reported.

## Results and deviations (added after testing, 2026-11-10)

Deviations from the plan above:
- Model B's feature list drops v1's `ey_vs_sector` / `fcfy_vs_sector`: once every input is ranked within its sector, they carry the same information as `ey` / `fcfy`.
- Calibration hit rates come from training-period rows of the same horizon, as planned. The deployed page instead maps each score decile to the out-of-sample test-window decile table. This is possible because Model A fits nothing.
- Universe coverage: about 970 names per date on average. There were 217 names in Jan 2010 and 656 in Jan 2011 (thin price history). From 2012 on there are 1,000. Of those, S&P members with data number 296 in 2012 and 485 in 2026.
- Residual survivorship bias: non-S&P names that delisted or were acquired before today are missing, because only today's SEC ticker list is free. Historical S&P members are included when Yahoo still serves their prices.

Outcome: Model A met the decision rule. Its wide rank IC overlap-adjusted t was above 2 at 6, 12, 48 and 60m, and its S&P t was 2.47 at 60m. Its S&P rank IC beats v1 at every horizon. Model B did not reach t>2 anywhere and is not deployed. Most of the edge comes from 2020–2022. Full numbers are in cache/model_v2_results.json (local), and the page shows the table.
