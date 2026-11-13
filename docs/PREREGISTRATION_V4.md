# Pre-registration: G1 v4 (full-cycle quant engine, business-intelligence overlay, execution rules)

**Written and committed 2026-11-12 22:15 PST (America/Los_Angeles), before any v4 feature, score or test result was computed and before `features_v2.py` was re-run.**
- v4 supersedes docs/PREREGISTRATION_V3.md, which was committed earlier the same evening. No v3 test was ever run.
- Results are appended below the line at the end. Nothing above that line may change after testing.
- Formulas come from Gary A's v4 spec. Anything the spec leaves open is pinned down here, before testing. Nothing will be tuned after results are seen.

## 1. Data (free only)

- **Yahoo** daily adjusted close, close and volume.
- **SEC XBRL companyfacts.** Point-in-time rule: the first-filed value for each period, usable 2 days after filing, missing if older than 550 days. Filing dates come from the `filed` date of each quarterly net-income fact.
- **SEC "Insider Transactions Data Sets"** (quarterly bulk Form 3/4/5, free) for the Form 4 cluster. They run through 2026 Q3 at writing.
- **FRED keyless CSVs.**
  - `BAMLH0A0HYM2` (HY OAS, %): the free history starts 2023-11-13.
  - `T10Y2Y`: shown only, not used in any rule.
- **Danelfin.** Only the five sub-scores already in Gary's uploaded portfolio CSVs (AI Score, Fundamental, Technical, Sentiment, Low Risk). Zero API calls. Display only, and only on Gary's pages.

## 2. Ranking conventions (same as v2/v3)

- **Universe:** the point-in-time wide universe `univ` (price ≥ $5, top 1,000 by market cap at each month-end).
- **Ranking:** inputs become per-date percentile ranks in 0..1 (pandas `rank(pct=True)`). "−" inputs use 1 − rank. Missing = 0.5 after ranking.
- **Scope:** "within-sector" means inside (date, SIC sector) using the 12 v2 SIC sectors. "Universe-wide" means inside the date.

## 3. Raw features (point-in-time at month-end t)

New in v4 relative to v2 (v3 definitions are carried over unchanged where named):

- **`fcf = cfo − capex`.** fcf_conv = fcf / max(ni, 1e-6), as written in the spec. Note: positive-FCF loss-makers therefore rank high. Kept untuned.
- **`roic_5y_med`.** Median of the monthly roic over the trailing 60 month-ends (minimum 24).
- **`inc_roic_3y` = (EBIT_t − EBIT_{t−3y}) / (IC_t − IC_{t−3y}).**
  - IC = equity + debt − cash.
  - The t−3y values are TTM/instant values for the period ending about 3 years before the latest period (point-in-time `near`).
  - Missing if ΔIC ≤ 0.
- **`non_op_investments`** = LT + EM + ST, where:
  - LT = first available of [LongTermInvestments, MarketableSecuritiesNoncurrent]
  - EM = EquityMethodInvestments
  - ST = first available of [ShortTermInvestments, MarketableSecuritiesCurrent]
  - Each part counts as 0 if missing.
- **`adj_ev`** = max(mcap + debt − cash − non_op_investments, 0.25·mcap).
  - fcfy_adj_ev = fcf / adj_ev.
  - ey_adj_ev = EBIT / adj_ev.
- **`ey_vs_hist`** (v2, EBIT/EV vs its own 5-year median). Gated term = ey_vs_hist × I[om_trend ≥ 0]. If om_trend is missing the gate is closed (0).
- **`inc_gm`** = gross margin (TTM) − gross margin one year earlier.
- **`def_rev_g1`.** Deferred revenue / contract liabilities growth over one year.
  - DR = first available of [ContractWithCustomerLiability, DeferredRevenue], else ContractWithCustomerLiabilityCurrent + ContractWithCustomerLiabilityNoncurrent, else DeferredRevenueCurrent + DeferredRevenueNoncurrent.
  - def_rev_g1 = DR_t / DR_{t−1y} − 1, needing DR_{t−1y} > 0.
- **`rd_roi`** = (rev_t − rev_{t−1y}) / R&D_{t−1y}.
  - R&D = TTM ResearchAndDevelopmentExpense (or ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost).
  - Missing if prior R&D ≤ 0 or missing.
- **`rule_of_40`** = rev_g1 + fcf/rev.
- **`post_filing_drift`** (as in v3):
  - f = the latest quarterly filing date with f + 7d ≤ t and t − f ≤ 120d.
  - W = the first 5 trading days dated ≥ f.
  - drift = (adj at the end of W / adj on the day before f − 1) × (mean volume over W / mean volume over the 50 prior days).
- **`vcp_ratio`** = sd(20-day log returns) / sd(120-day log returns).
- **`up_down_vol_50d`** = up-day dollar volume / down-day dollar volume over 50 trading days.
- **`beta_down`.** Downside beta on 104 weekly log returns, using SPY-down weeks only (≥ 20 of them).
- **`cvar_5`** = mean of the worst 3 weekly simple returns in 52 weeks.
- **`f_score`.** 9-test Piotroski on TTM vs one year earlier. Score = 9 × passed / available, if ≥ 5 tests are available.
- **`eq_assets`, `roe_stab`.** roe_stab = −sd of monthly roe over 60 month-ends (minimum 24).
- **`sma40_below`** = I[weekly adj < 40-week SMA].
- **`form4_cluster`** = 1 if, in the 90 days up to t (by Form 4 *filing* date), at least 3 distinct reporting owners filed open-market purchases.
  - An open-market purchase is non-derivative transaction code "P".
  - Issuer matched by CIK.
  - Otherwise 0. Live: computed from the latest bulk quarter available. Days after that quarter count as having no filings, and the page says so.

## 4. Sector momentum multiplier

At each date, for each of the 12 SIC sectors:
- m_s = median over its `univ` names of mom_6_1 / vol_1y (6-month risk-adjusted momentum).
- Sectors with fewer than 5 such names get mult 1.0.
- The others are ranked ascending, k = 1..n: sector_mult = 0.85 + 0.30·(k − 1)/(n − 1). Ties take the average rank.

## 5. Sleeves (0..1, except S4 can reach 1.15 and S5 1.05)

- **S1 Quality** (within-sector): mean(+roic_5y_med, +inc_roic_3y, +fcf_conv, +gpa, −accruals, −dil_3y).
- **S2 SOTP-adjusted EV value** (within-sector): mean(+fcfy_adj_ev, +ey_adj_ev, +gated ey_vs_hist).
- **S3 Growth, backlog & inflection** (within-sector): mean(+sue, +rev_accel, +om_trend, +inc_gm, +rule_of_40, +def_rev_g1, +rd_roi, +post_filing_drift).
- **S4 Trend & VCP coil** = mean(+mom_12_1, +dd_52w, −vcp_ratio, +up_down_vol_50d) × sector_mult. Each input rank = 0.5·universe rank + 0.5·within-sector rank.
- **S5 Left-tail shield** (universe-wide) = mean(−lev, +intcov, −beta_down, +cvar_5, +f_score) + 0.05·form4_cluster.
- **Financials override** (SEC SIC 6000–6799):
  - ey, ey_adj_ev, gpa, roic, roic_5y_med, inc_roic_3y, lev and intcov are masked to missing before ranking.
  - S1 = mean(+roe, +roa, +roe_stab, −dil_1y).
  - S5 = mean(+eq_assets, +bm, −beta_down, +cvar_5, +f_score) + 0.05·form4_cluster.
  - Both are ranked within the SIC 6000–6799 group at that date.
  - S2, S3 and S4 use the normal formulas, with the masked inputs reading 0.5.
- **Multi-class aliasing** (display and lookup only; backtest rows unchanged so A and S_quant see identical rows):
  - Tickers sharing an SEC CIK (company_tickers.json) use the primary class's company-level fundamentals. The primary is the class with the most panel rows.
  - Dollar and per-share figures are scaled by the class's own price relative to the primary's.
  - Price features are always the ticker's own.

## 6. Axes, regime and master quant score

- **Axes:**
  - U = 100·(0.35·S3 + 0.35·S4 + 0.30·mean(S1, S2))
  - D = 100·(0.50·S5 + 0.30·S1 + 0.20·S2)
- **Inputs at t:**
  - SPY weekly adj vs its 40-week SMA, from weekly bars up to t.
  - HY = the last BAMLH0A0HYM2 value dated ≤ t − 1 day.
  - breadth = the share of `univ` names at t with sma40_below = 0, among names where it is known.
- **Regime:**
  - **Risk-Off** if SPY < SMA40 or HY > 5.5.
  - **Risk-On** if not Risk-Off and SPY > SMA40 and HY < 4.5.
  - **Neutral** otherwise.
  - When HY is unavailable (before 2023-11-13), its clauses are dropped, so Risk-On = SPY > SMA40.
- **S_quant** = 0.65U + 0.35D (Risk-On), 0.50U + 0.50D (Neutral), 0.30U + 0.70D (Risk-Off).
- **Cash shield** (guidance only; it never changes S_quant and is not backtested):
  - **Bear Preservation** = SPY < SMA40 AND breadth < 0.35.
    - Recommended T-bill (SGOV) reserve = 30% + 20% × clamp((0.35 − breadth)/0.15, 0, 1). That is 30% at breadth 0.35, rising to 50% at 0.20 or below.
    - New buys are paused: STRONG BUY and ACCUMULATE verdicts show "(buys paused)".
  - **CAPITULATION BUY** takes precedence and needs all of:
    - SPY ≥ 15% below its 52-week high
    - breadth now > 0.40, while the minimum weekly breadth over the prior 13 weeks was < 0.35 (it crossed up out of a bear)
    - HY now ≤ its 13-week peak − 0.50 pp
  - Live weekly breadth is computed at build over the current top-1000 names' price files.
  - Market Weather labels: Risk-On "Sunny", Neutral "Cloudy", Risk-Off "Storm Warning", Bear Preservation "Storm: preserve cash", CAPITULATION BUY "Clearing after the storm".
  - Otherwise the reserve is 0% (100% equities).

## 7. Price-only fallback

- **S_price** = 100·clamp(mean(+mom_12_1, +dd_52w, −vcp_ratio, −beta_down, +cvar_5) − 0.15·sma40_below, 0, 1).
- Inputs are universe-wide ranks; live, they are ranked against the build date's 101-point universe quantiles.

## 8. Labels: Shumway haircut and turnover drag

- **Base label:** forward excess return vs SPY at h = 6/12/24/36/48/60 months. Proceeds stay in SPY if trading stops.
- **Haircut** (applies to every model):
  - Trigger: the stock's last price is before t + h AND at least 10 days before the price-data end (a real delisting), AND its last monthly panel row on or before the exit has dd_52w < −0.50 or roa < 0.
  - Then y → 0.7·(1 + y) − 1.
- **Turnover drag** (model-specific, applied to top-decile metrics):
  - τ = the mean monthly one-way turnover of the model's top decile (the share of this month's top-decile names that were not in last month's top decile).
  - drag_h = 2 × 0.0010 × τ × h (sell and buy at 10 bps each, monthly, over h months).
  - It is subtracted from every top-decile label before computing p10 and the top-bottom spread.
  - Rank IC is unaffected.

## 9. Test and pass rule

- **Sample:** the wide universe, month-ends from 2014-01 with a label. S_quant has no fitted parameters, so the test is out-of-sample by construction. A is v2 composite A, unchanged.
- **Metrics:**
  - rank IC with overlap-adjusted t = mean/sd·√(n_dates/h)
  - **top-decile p10** = the mean over dates of the 10th percentile of y among the top-decile names
  - top-minus-bottom decile
  - AUC
- All are reported on (i) haircut + drag labels (primary) and (ii) raw labels.
- **PASS needs all three, on haircut + drag labels:**
  - (a) IC(S_quant) > IC(A) at ≥ 4 of 6 horizons.
  - (b) S_quant IC t > 2.5 at both 12m and 24m.
  - (c) top-decile p10 (after drag) of S_quant > A's at ≥ 4 of 6 horizons.
- **If PASS:** S_quant is the live quant score. Bands and P(beat) come from its out-of-sample per-date decile table, as for A.
- **If FAIL:** A remains the live quant score. U, D and S_quant are not shown as validated scores (U and D may appear only as labelled, untested descriptive bars). Every non-model feature still ships.
- **Also reported:** U, D and S_price.

## 10. Business-intelligence overlay (not backtestable, unvalidated)

- **Built by `pipeline/intel_dossiers.py`:**
  - cache `cache/dossiers/{T}.json`, 14-day TTL
  - names covered: holdings in configured books, the top-30 finalists by live quant score, and on-demand `analyze_ticker.py T`
- **Free public sources only:**
  - SEC XBRL facts and SEC submissions (recent 8-K/10-K/10-Q with links)
  - optional analyst notes in `cache/dossiers/notes/{T}.json`
  - Every note must cite URLs. A note may override a sub-score only with a cited source.
- **The overlay is not point-in-time.** It cannot be backtested and is an unvalidated overlay.
- **Sub-scores** (sum = f_strat, clamped to [−10, +10]). Evidence rules are fixed here; thin or missing evidence scores 0 and says so.
  1. **Moat vs disruption** (−2..+2):
     - +1 if roic_5y_med ≥ 0.15
     - +1 if gross margin ≥ its sector's 75th percentile and om_stab is in the top half of its sector
     - −1 if rev_g1 < 0 and inc_gm < 0
     - −1 if 3-year revenue CAGR < 0
  2. **Hidden stakes / SOTP** (0..+3):
     - non_op_investments / mcap ≥ 0.10 → +1, ≥ 0.25 → +2, ≥ 0.50 → +3
     - cited to the XBRL facts and the filing accession
     - A cited analyst note may add a private or subsidiary stake value (USD), which is subtracted in the dossier's own adj_ev display. It never enters S_quant.
  3. **Talent & R&D** (−1..+2):
     - +1 if R&D / revenue ≥ the sector median (among R&D reporters) and rd_roi > 0
     - +1 if rd_roi is in the top quartile of R&D reporters
     - −1 if R&D > 0 and rd_roi < 0
     - 0 if no R&D is reported
  4. **Pricing power & backlog** (−2..+2):
     - +1 if inc_gm > 0
     - +1 if def_rev_g1 > rev_g1 and def_rev_g1 > 0
     - −1 if inc_gm < −0.02
     - −1 if def_rev_g1 < −0.10
  5. **Variant perception gap** (−2..+2): gap = mean(S1, S3) − (1 − S2), i.e. business quality/growth rank minus the rank implied by its cheapness. ≥ 0.30 → +2, ≥ 0.15 → +1, ≤ −0.30 → −2, ≤ −0.15 → −1.
- **Text fields** consensus_view, variant_edge, top_threats and catalysts are one-liners built from these facts and recent SEC filings, with links. No invented facts.
- **Score definitions:**
  - Base = S_quant if PASS, else 100 × A's universe percentile.
  - **S_v4 = clamp(base + 1.5·f_strat, 0, 100)**, labelled "includes unvalidated analyst-style judgment".
  - S_quant/base and S_v4 are shown separately.
  - Verdicts, sizes and stops use only the validated live quant score.

## 11. Execution rules (display only, "model estimates, not advice")

- **pct.** The live quant score's percentile in the current universe. Bands are its out-of-sample 12m decile bands (excess vs SPY; dollar targets assume a flat S&P 500).
- **Price targets (12m):**
  - Bear = P(1 + p10)
  - Base = P(1 + p50)
  - Bull = P(1 + p90)
- **Verdict**, first match wins:
  1. **SELL / BROKEN:** pct ≤ 0.20, or (P < 40-week SMA and dd_52w < −0.30).
  2. **CLIMAX TRIM:** trend40 ≥ 0.50 (≥ 50% above the 40-week SMA) and rev_1m ≥ 0.15.
  3. **ACCUMULATE (Staggered):** upside test and rev_1m > 0.15. The card adds: "Buy 50% of target weight now, add the rest on a pullback to the 40-week SMA."
  4. **STRONG BUY:** upside test.
  5. **HOLD:** everything else.
  - The upside test is U ≥ 75 and pct ≥ 0.80 if PASS, otherwise pct ≥ 0.80.
  - In Bear Preservation, items 3–4 show "(buys paused)".
- **Half-Kelly size:**
  - p = the 12m decile hit rate; b = p90/|p10| from the 12m decile bands.
  - f = max(0, (p·b − (1 − p))/b)/2 × min(1, 0.25/σ_down), capped at 10%.
  - σ_down = √52·√mean(min(r_w, 0)²) over 52 weekly simple returns.
  - f is halved if the estimated next earnings date is ≤ 7 days away.
  - Estimated next earnings = the earliest of (each of the last 4 quarterly SEC filing dates + 364 days) that is ≥ today. This is an SEC-based estimate, because free Yahoo earnings calendars need a session crumb.
- **3-stage ratchet stop.** E = the purchase price when the book CSV has one (Gary's CSVs do; friend CSVs may add a third column), else none.
  - Stage 1: max(SMA40w, P·(1 + cvar_5)).
  - Stage 2: once P/E − 1 ≥ +20%, the stop becomes max(Stage 1, E) (breakeven).
  - Stage 3: once P/E − 1 ≥ +40%, the stop becomes max(Stage 2, EMA10w), where EMA10w is the 10-week EMA of weekly closes (α = 2/11, seeded with the first close).
  - Without E, only Stage 1 is shown.
- **Portfolio Health:**
  - Warn if any SIC sector exceeds 35% of book value (shares × price, or equal weight if no shares).
  - Warn for any holding pair whose Pearson correlation of the last 52 weekly simple returns (≥ 40 overlapping weeks) exceeds 0.80: "Warning: A and B are moving identically. Check diversification."

---
## Results
(appended after testing)
