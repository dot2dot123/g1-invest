# Pre-registration: "Buffett & Munger" and "Magic 15" style scores (written before any test)

These scores are rule-based proxies built from the investors' published principles. They are not the investors' actual
views or holdings. Every input is point-in-time, from the G1 v2 panel (SEC companyfacts plus Yahoo prices; 2-day filing lag),
plus the Yahoo ^TNX 10-year Treasury yield.

## Buffett & Munger (B&M), 0–10 points, absolute rules
A missing input scores half of that rule's points. History stats use the ticker's own monthly panel rows from the prior 60 months, with at least 24 rows required.

| Rule | Points |
|---|---|
| Durable returns: 5y median ROE ≥ 15% and 5y minimum ROE ≥ 10% → 2; else 5y median ROE ≥ 12% → 1 | 2 |
| Low leverage: debt/assets ≤ 0.30 → 1 | 1 |
| Consistent margins: operating-margin stability (−sd of quarterly operating margin) ≥ −0.03 → 1 | 1 |
| Consistent profits: 5y minimum ROA > 0 → 1 | 1 |
| Moat proxy, gross margin: ≥ 40% → 2; ≥ 25% → 1 | 2 |
| Owner-friendly share count: 3y share change ≤ 0 → 1 | 1 |
| Sensible price, owner earnings (FCF = CFO − capex) yield vs 10y Treasury: FCF/mcap ≥ yield → 2; ≥ 0.6 × yield → 1 | 2 |

"Simple, understandable business" is left out because it is subjective.

## Magic 15, 0–10 = 10 × mean of six pillars
Each pillar is the mean of per-date percentile ranks (0–1) of its inputs, taken across the top-1000 universe (not within sector). A missing input counts as 0.5. Signs show direction.

| Pillar | Inspired by | Inputs |
|---|---|---|
| deep_value | Klarman, Pabrai | EBIT/EV +, FCF/mcap +, book/price +, EBIT/EV vs own 5y median + |
| downside | Marks, Karsh | debt/assets −, interest coverage +, 3y max drawdown (less negative is better) +, 1y volatility − |
| macro_trend | Druckenmiller | 12-1 momentum +, 40-week trend +, distance from 52-week high + |
| durable_growth | Thiel, Botha, Lin, Fenton, Cohler | 3y revenue CAGR +, gross margin +, 1y revenue growth +, operating-margin trend + |
| compounders | Ackman, Combs, Weschler | ROIC +, gross profit/assets +, margin stability +, 3y share change − |
| yield_credit | Black, Rowan | FCF/mcap +, interest coverage +, debt/assets −, accruals − |

R&D intensity is not in the free panel, so it is left out.

## Test (fixed before running)
- Rebalance dates: month-ends from 2014-01, using only rows whose y_h is known. Horizons are 6, 12, 24, 36, 48 and 60m.
- Universes: wide (`univ`) and S&P members within it. The scores are fixed rules with no fitting, so there is no training step.
- Metrics:
  - Pooled AUC for beating SPY.
  - Rank IC, with t-stat = mean/sd × √(n_dates/h).
  - Top-minus-bottom decile excess return.
  - Mean IC per calendar year.
- Redundancy checks:
  - Per-date Spearman correlation with the G1 v2 composite (A).
  - Partial IC: IC of the score after per-date OLS-residualizing its rank on A's rank.
  - Stacked check: IC of the 50/50 rank blend minus IC of A alone, with an overlap-adjusted t on the per-date difference.
- Ablation: drop one pillar or rule at a time, then report ΔIC.
- Weight sensitivity: 200 Dirichlet(1) random pillar weightings (seed 7). Report the 5th, 50th and 95th percentile ICs. Equal weights are kept regardless.
- Style conflict: mean per-date Spearman correlation between pillars, plus each pillar's stand-alone IC.

## Verdict rule, per score
- **KEEP:** combined rank IC t > 2 at one or more horizons (wide or S&P), AND partial IC vs A > 0 with t > 1.5 at two or more horizons.
- **SIMPLIFY:** not KEEP, but dropping one pillar raises wide IC at four or more of the six horizons, or one pillar alone has t > 2 at two or more horizons. Recommend the simpler form; do not deploy it unseen.
- **DROP:** otherwise.

Either way the boxes are display-only and never feed G1's P(beat SPY). The page states the verdict.
