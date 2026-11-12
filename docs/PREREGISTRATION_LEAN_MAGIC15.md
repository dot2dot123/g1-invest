# Pre-registration: lean Magic 15 (written and committed before any test)

**Why this version.** In the earlier pre-registered pressure test (docs/PREREGISTRATION_STYLE_SCORES.md), the quality-compounders pillar carried most of the signal, and downside was the second-largest contributor in the drop-one test. Deep value and durable growth both lowered IC at every horizon, and deep value vs trend correlated at −0.23. The weights below are fixed a priori. No further weight search will be run.

**Definition.** "Magic 15 (lean: quality compounders + downside protection)", scored 0–10 as 10 × the mean of two equal-weight pillars. Each pillar is the mean of per-date percentile ranks (0–1) across the top-1000 universe. A missing input counts as 0.5. Inputs are point-in-time from the G1 v2 panel, the same inputs as the existing pillars:

- **Quality compounders** (Ackman, Combs, Weschler):
  - ROIC (EBIT / invested capital) +
  - Gross profit / assets + (profitability and pricing-power proxy)
  - Operating-margin stability (−sd of quarterly operating margin, so steadier is higher) +
  - 3-year share-count change − (low dilution or buybacks)
- **Downside protection** (Marks, Karsh):
  - Debt / assets −
  - Interest coverage (log1p EBIT / interest) +
  - 3-year maximum drawdown + (shallower is better)
  - 1-year volatility −

Deliberately left out, because they cancelled out or added little in the earlier test:
- Deep value (Klarman, Pabrai)
- Durable growth (Thiel, Botha, Lin, Fenton, Cohler)
- Macro trend (Druckenmiller)
- Yield and credit value (Black, Rowan)

The score stays a rule-based proxy of published principles, not those investors' views. It is display-only and never changes G1's P(beat SPY).

**Test.** Same as the earlier style test:
- Month-ends from 2014-01, at 6, 12, 24, 36, 48 and 60m.
- Universes: wide top-1000 and S&P members.
- Metrics:
  - AUC
  - Rank IC with overlap-adjusted t
  - Top-minus-bottom decile
  - Per-year IC
  - Partial IC vs the G1 v2 composite A
  - 50/50 rank blend with A minus A alone
- Compared side by side with the current Magic 15, Buffett & Munger and A.

**Decision rule.** SWAP only if all three hold:
- (a) Wide rank IC overlap-adjusted t > 2 at one or more horizons.
- (b) The lean version's wide rank IC is no more than 0.01 below the current Magic 15's at four or more of the six horizons.
- (c) Partial IC vs A is above 0 with t > 1.5 at two or more horizons.

Otherwise the current Magic 15 stays on the page.

## Results (added after testing, 2026-11-11)

Wide top-1000 universe, rank IC (overlap-adjusted t):

| h | Lean M15 | Old M15 | B&M | G1 composite A | Lean partial vs A |
|---|---|---|---|---|---|
| 6m | .048 (2.22) | .041 (1.85) | .053 (3.14) | .036 (2.41) | .034 (1.41) |
| 12m | .068 (2.45) | .047 (1.70) | .070 (2.89) | .049 (2.24) | .051 (1.58) |
| 24m | .106 (2.85) | .068 (2.09) | .096 (2.78) | .076 (2.20) | .080 (1.76) |
| 36m | .130 (3.40) | .100 (2.73) | .117 (4.18) | .090 (2.39) | .101 (1.88) |
| 48m | .144 (3.50) | .121 (2.69) | .137 (3.73) | .104 (2.64) | .107 (1.70) |
| 60m | .142 (2.98) | .107 (2.12) | .135 (3.36) | .108 (2.76) | .103 (1.43) |

Decision rule:
- (a) Passed: t > 2 at all six horizons.
- (b) Passed: the lean IC is above the old version's at all six horizons.
- (c) Passed: partial t > 1.5 at 12, 24, 36 and 48m.

Result: **SWAPPED.**

Caveats:
- The top-minus-bottom decile spread is smaller than the old version's at 24–60m (+1.7% to +7.6% vs +0.3% to +10%). The lean version sorts the middle of the list better, but its extremes are not stronger.
- The years 2016 and 2020 are negative at 6–12m.
- Same survivorship-bias caveat as G1.
- 48–60m results rest on few independent periods.
- The lean design was informed by the earlier test on the same data, so this is not a fully independent out-of-sample confirmation.

Full output: cache/lean_test_results.json (local).
