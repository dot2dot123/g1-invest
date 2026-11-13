# Pre-registration: G1 v3 asymmetric upside/downside engine

**Written and committed 2026-11-12 22:05 PST (America/Los_Angeles), before any v3 feature, score or test result was computed.**
`features_v2.py` had not been re-run with the v3 features when this was committed.
Results are appended below the line at the end. Nothing above that line may change after testing.

The formulas come from Gary A's v3 spec. Anything the spec leaves open is pinned down here, before testing, in the simplest parameter-light way. Nothing will be tuned after results are seen.

## 1. Data (free only)

- **Prices:** Yahoo daily close, adjusted close and volume, as in v1/v2.
- **Fundamentals:** SEC XBRL companyfacts.
  - Point-in-time rule: the first-filed value for each period, usable 2 days after filing. Values older than 550 days are treated as missing.
- **SEC filing dates:** the `filed` date of each quarterly net-income fact (10-Q, or 10-K for Q4) in companyfacts.
- **Macro:** FRED keyless CSVs `BAMLH0A0HYM2` (ICE BofA US High Yield OAS, %) and `T10Y2Y`, plus Yahoo `^TNX` (10y yield, %; already cached).
- **Known limitation, checked before writing this:** FRED's free CSV of BAMLH0A0HYM2 only goes back to 2023-11-13 (ICE licensing). T10Y2Y goes back to 1976. Section 6 states how the backtest handles the missing HY history.

## 2. Ranking conventions

- Universe and dates: the wide point-in-time universe (`univ`: price ≥ $5 and top 1,000 by market cap at each month-end), as in v2.
- Every input is converted to a per-date percentile rank in 0..1 (pandas `rank(pct=True)`, average ties).
  - "−" inputs use 1 − rank.
  - A missing input becomes 0.5 after ranking.
- "Within-sector" means ranks inside (date, sector), using the v2 SIC→sector map. "Universe-wide" means ranks inside the date.
- A sleeve = mean of its signed input ranks. Sleeves are in 0..1.

## 3. New raw features

All are point-in-time, computed at each month-end t (and live in the browser where possible).

- `fcf = cfo − capex` (TTM). Missing capex counts as 0, as in v2.
- `fcf_conv = fcf / max(ni, 1e-6)`, exactly as in the spec.
  - Note: when NI ≤ 0 the denominator is 1e-6, so positive-FCF loss-makers rank high and negative-FCF loss-makers rank low. This is kept as written, untuned.
- `fcfy_ev = fcf / EV` (missing if EV ≤ 0).
- `roic_5y_med`: median of the monthly `roic` values over the trailing 60 month-ends (minimum 24).
- `rule_of_40 = rev_g1 + fcf / rev` (missing if rev ≤ 0).
- `gated_ey_vs_hist = ey_vs_hist × I[om_trend ≥ 0]`.
  - If `om_trend` is missing the gate is closed (0).
  - If `ey_vs_hist` is missing the input is missing.
- `post_filing_drift = r × surge`, built from the latest quarterly filing date f with f + 7 days ≤ t and t − f ≤ 120 days (otherwise missing):
  - W = the first 5 trading days dated ≥ f.
  - r = adj close on the last day of W / adj close on the last trading day before f − 1.
  - surge = mean volume over W / mean volume over the 50 trading days before f.
- `vcp_ratio = sd(daily log return, last 20 days) / sd(daily log return, last 120 days)`.
- `up_down_vol_50d = Σ close·volume on up days / Σ close·volume on down days`, over the last 50 trading days.
  - Up/down is the sign of the adjusted daily return.
  - Missing if there were no down days.
- `beta_down = cov(r_i, r_spy | r_spy < 0) / var(r_spy | r_spy < 0)`.
  - Uses weekly log returns over the trailing 104 weeks. Needs ≥ 20 down-market weeks.
- `cvar_5 = mean of the worst 3 weekly simple returns over the trailing 52 weeks`. This is negative; higher means a better tail.
- `f_score`: 9-point Piotroski on TTM values vs the same values one year earlier (point-in-time `near(end − 365d)`).
  - The nine tests:
    1. ROA > 0
    2. CFO > 0
    3. ΔROA > 0
    4. CFO > NI
    5. Δ(long-term debt / assets) < 0
    6. Δ(current assets / current liabilities) > 0
    7. dil_1y ≤ 0
    8. Δ gross margin > 0
    9. Δ(revenue / assets) > 0
  - Score = 9 × points / tests available, if ≥ 5 tests are available; otherwise missing.
- `eq_assets = equity / assets`.
- `roe_stab = −sd(monthly roe over the trailing 60 month-ends)` (minimum 24).
- `sma40_below = I[weekly adj close < 40-week SMA]`.

## 4. Five sleeves (0..1)

- **S1 Quality** (within-sector): mean(+roic_5y_med, +fcf_conv, +gpa, −accruals, −dil_3y).
- **S2 Gated EV value** (within-sector): mean(+fcfy_ev, +ey, +gated_ey_vs_hist).
- **S3 Growth & inflection** (within-sector): mean(+sue, +rev_accel, +om_trend, +rule_of_40, +post_filing_drift).
- **S4 Trend & VCP coil**: mean(+mom_12_1, +dd_52w, −vcp_ratio, +up_down_vol_50d).
  - Each input rank = 0.5 × universe-wide rank + 0.5 × within-sector rank, each signed, and each 0.5 if missing.
- **S5 Left-tail shield** (universe-wide): mean(−lev, +intcov, −beta_down, +cvar_5, +f_score).

**Financials override** (SEC SIC 6000–6799, which includes banks, insurers and REITs):
- ey, gpa, roic (so roic_5y_med), lev and intcov are masked to 0.5 wherever they appear.
- S1 for these firms = mean(+roe, +roa, +roe_stab, −dil_1y). Ranks are taken within the SIC 6000–6799 group at that date.
- S5 for these firms = mean(+eq_assets, +bm, −beta_down, +cvar_5, +f_score). Ranks are also taken within the SIC 6000–6799 group.
- S2 for these firms = mean(+fcfy_ev, 0.5 [masked ey], +gated_ey_vs_hist). Within-sector, as for everyone else.
- S3 and S4 are unchanged.

**Multi-class aliasing:**
- Tickers that share an SEC CIK (from SEC company_tickers.json; for example GOOGL/GOOG, BRK.A/BRK.B) use the primary class's company-level fundamentals.
- The primary class is the one in the build's panel with the most rows; ties go to the first SEC listing.
- Company-level ratios (yields, ROIC and so on) are therefore the same for both classes. Per-share and dollar figures shown for the alias are scaled by the alias's own live price relative to the primary's.
- Price features are always the ticker's own.
- In the backtest panel, rows are left as they are, so A and v3 are scored on the same rows.

## 5. Axes and master score

- **U** = 100 × (0.35·S3 + 0.35·S4 + 0.30·mean(S1, S2))
- **D** = 100 × (0.50·S5 + 0.30·S1 + 0.20·S2)

## 6. Macro regime (point-in-time)

At date t:
- SPY: weekly adjusted close at t vs its 40-week SMA.
- HY = the latest BAMLH0A0HYM2 observation dated ≤ t − 1 day.
- ΔTNX13 = ^TNX at t − ^TNX at t − 91 days (percentage points).

Regime rules:
- **Risk-Off** if SPY < SMA40, or HY > 5.5, or ΔTNX13 > +0.75.
- **Risk-On** if not Risk-Off, SPY > SMA40, and HY < 4.5.
- **Neutral** otherwise.

**Missing HY history (before 2023-11-13 on free FRED data):** the HY clauses are dropped for those dates.
- Risk-Off then uses only SPY and ΔTNX13.
- Risk-On needs only SPY > SMA40 with no Risk-Off trigger.
- This was decided before testing. It means Neutral is effectively never used before 2023-11. Live pages always have HY.
- T10Y2Y is fetched and shown in the Market Weather banner for context only. It is not used in any rule, because the spec gives no rule for it.

Master score:
- **S_v3** = 0.65U + 0.35D (Risk-On), 0.50U + 0.50D (Neutral), 0.30U + 0.70D (Risk-Off).

**Market Weather labels:** Risk-On = "Sunny", Neutral = "Cloudy", Risk-Off = "Storm Warning".

## 7. Price-only fallback (replaces the v1 logistic for names with no usable fundamentals)

- **S_price** = 100 × clamp(mean(+mom_12_1, +dd_52w, −vcp_ratio, −beta_down, +cvar_5) − 0.15 × sma40_below, 0, 1).
  - Inputs are universe-wide percentile ranks (missing = 0.5).
  - Live in the browser, a feature is ranked against the build date's 101-point universe quantiles (same `qpct` as v2).

## 8. Labels and the Shumway delisting haircut

- The label is the forward excess return vs SPY at h = 6, 12, 24, 36, 48 and 60 months, as in v2. Proceeds are frozen in SPY if trading stops early.
- **Haircut:** if the stock's last price comes before t + h (a mid-horizon exit) AND at least 10 days before the price data ends (a real delisting, not the data edge), AND its last monthly panel row on or before the exit has dd_52w < −0.50 or roa < 0, the label becomes 0.7 × (1 + y) − 1.
- The haircut labels are the primary labels for every model compared (A, S_v3, U, D, S_price). Un-haircut results are reported too, for continuity.

## 9. Test and pass criteria

- **Sample:** wide universe, month-ends from 2014-01 with a label available. S_v3 has no fitted parameters, so the walk-forward is simply out-of-sample by date. v2 composite A is computed exactly as in v2.
- **Metrics per horizon:**
  - rank IC (Spearman per date, then the mean) with overlap-adjusted t = mean / sd × √(n_dates / h)
  - top-minus-bottom decile
  - **p10** = the mean over dates of the 10th percentile of y among that date's top-decile names (higher is better: a less bad left tail for the names you would buy)
  - AUC
- **PASS (all on haircut labels) requires all three:**
  - (a) IC(S_v3) > IC(A) at ≥ 4 of 6 horizons.
  - (b) S_v3 IC t > 2.5 at both 12m and 24m.
  - (c) p10(S_v3) > p10(A) at ≥ 4 of 6 horizons ("improves p10").
- **If PASS:** S_v3 becomes the live score. P(beat SPY) and the p10/p50/p90 bands come from its walk-forward per-date decile table, as was done for A.
- **If FAIL:** v2 composite A stays the live score. U and D are not shown as scores. The non-model features still ship on top of A.

## 10. Execution rules (display only, labelled "model estimates, not advice")

All bands are the live score's out-of-sample decile bands for the selected horizon. They are excess returns vs SPY, so dollar targets assume a flat S&P 500.

- **Price targets:** Bear = P × (1 + p10), Base = P × (1 + p50), Bull = P × (1 + p90).
- **Hard stop / invalidation** = max(40-week SMA, P × (1 + cvar_5)). If this is at or above P, the card says the stock is already below its invalidation level.
- **Verdict** (live-score percentile in the wide universe, pct):
  - ACCUMULATE (Staggered) if the upside test holds AND rev_1m > 0.15. The upside test is U ≥ 75 if v3 passed, otherwise pct ≥ 0.75. The card then says: "Buy 50% of target weight now, add the remainder on a pullback to the 40-week SMA."
  - else ACCUMULATE if pct ≥ 0.80
  - else AVOID if pct ≤ 0.20
  - else HOLD
- **Half-Kelly size:**
  - Inputs: p = the 12m decile hit rate, and b = p90 / |p10| from the 12m decile bands.
  - f = max(0, (p·b − (1 − p)) / b) / 2 × min(1, 0.25 / σ_down), capped at 10%.
  - σ_down = annualised downside deviation of weekly returns over 52 weeks (√52 × √mean(min(r, 0)²)).
  - The spec ties size to "U, D": when v3 is live, p and b come from the S_v3 decile, which is built from U and D.
- **Pairwise correlation warning (Portfolio Health Card):**
  - Pearson correlation of the last 52 weekly simple returns, for every pair of holdings with ≥ 40 overlapping weeks.
  - Any pair with ρ > 0.80 triggers: "Warning: A and B are moving identically. Check diversification."

---
## Results
(appended after testing)
