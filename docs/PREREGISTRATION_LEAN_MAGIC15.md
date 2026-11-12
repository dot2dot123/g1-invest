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
