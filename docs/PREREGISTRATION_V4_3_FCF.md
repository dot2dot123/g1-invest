# G1 v4.3 free-cash-flow pillar: pre-registration

Committed: 2026-11-22 (PST), before any v4.3 backtest result was computed. Owner request: make free cash flow / owner
earnings a very important part of G1. Nothing below is tuned after results.

## 1. Data and point-in-time rules
Same panel, universe, dates and labels as v4.2 (docs/PREREGISTRATION_V4_2.md): cache/panel_v2.parquet, wide universe
(`univ`, top 1000 by market cap, price >= $5), month-ends, evaluation 2014-01 onward, labels y{h} = h-month return minus
SPY; primary labels = Shumway haircut + hysteresis turnover drag. FCF inputs come from local SEC companyfacts
(pipeline/fcf_features.py): first-filed values only, usable 2 days after filing, TTM sums, stale after 550 days.
Known limitation (same as v4.2): the price panel only holds tickers that still have Yahoo history, so firms that
delisted are missing (survivorship bias; the haircut never triggers). Results are relative comparisons on the same panel.

## 2. Features (per ticker, per date t, all known at t)
FCF_k = CFO_k - CapEx_k for the TTM period ending k years before the latest TTM (k = 0..5). EV = mcap + debt - cash.
- `oe_ev` owner-earnings yield = (FCF_0 - SBC_0) / EV (SBC = stock comp add-back; 0 if not reported)
- `fcf_avg3_ev` normalized FCF yield = mean(FCF_0..2) / EV
- `fcf_mc` FCF / market cap, `fcf_ev2` FCF / EV (reported, not in the pillar beyond the two yields above)
- `fcf_g3`, `fcf_g5` FCF CAGR over 3 / 5 years, clipped [-50%, +100%]; +100% if turned positive, -50% if FCF_0 <= 0
- `conv3` cash conversion = sum(FCF_0..2) / sum(NI_0..2), clipped [-1, 1.5] (1.5 if NI sum <= 0 < FCF sum)
- `fcfm0` FCF margin, `fcfm_std5` std of annual FCF margins over up to 6 years (min 3)
- `capex_cut` flag = capex/D&A fell below 0.7x its level 2 years earlier, is now < 1.0, and FCF rose (FCF flattered by
  under-investment)

## 3. FCF pillar P5
Within-(date, sector) percentile ranks, missing -> 0.5:
P5 = 0.35 x mean(rank oe_ev, rank fcf_avg3_ev) + 0.20 x mean(rank fcf_g3, rank fcf_g5) + 0.15 x rank min(conv3, 1.5)
   + 0.15 x rank fcfm0 + 0.15 x (1 - rank fcfm_std5) - 0.15 x capex_cut.
Financials (sector "Financials": SIC 6000-6799 excluding real estate 6500-6599 and REITs 6798) have no meaningful FCF:
P5 = 0.5 (neutral) and they are never FCF-gated. REITs and all other sectors use P5 as defined.

## 4. Variants (P1-P4 and the BM < 4 cap at 0.65 are unchanged from v4.2)
- (a) `V42` baseline.
- (b) `V43_eq` blend = (P1+P2+P3+P4+P5)/5.
- (c) `V43_heavy` blend = 0.35 x P5 + 0.1625 x (P1+P2+P3+P4).
- (d) `V43_gate` V42, then V = min(V, 0.35) when non-financial and (FCF_0 < 0 or P5 in the bottom quintile of its date).
Each blend -> per-date universe percentile -> BM cap -> score 0-100.

## 5. Metrics
Per horizon h in {6, 12, 24, 36} (48, 60 reported): mean per-date Spearman rank IC and overlap-adjusted t (v4.2
`evaluate`), top-decile mean excess vs SPY after drag, top-minus-bottom decile, top-decile p10, top-decile hit rate
(share of top-decile rows with y > 0). Hysteresis turnover (enter top 15%, hold to top 35%). Monthly-rebalanced
equal-weight top-30 portfolio from 2014-01: CAGR, excess CAGR vs SPY, max drawdown, downside capture (mean portfolio
return / mean SPY return in SPY-down months), 10 bps per side on one-way turnover.

## 6. Decision rule
Among (b), (c), (d) pick the one with the highest mean primary IC over 12, 24 and 36 months. It becomes G1 v4.3 iff ALL:
1. primary IC > V42's at 12, 24 and 36 months;
2. top-decile mean excess >= V42's at >= 2 of 12, 24, 36 months;
3. 12-month t >= 2.0;
4. top-30 max drawdown no more than 3 points worse than V42's, and downside capture no more than 0.05 higher.
Otherwise V42 stays live and the FCF features ship only as display/diagnostics. Note: three variants are tested, so
the chosen one carries some selection optimism.

## 7. Results (appended after the run; nothing above was changed)
