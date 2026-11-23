# G1 v4.3 (FCF + peer positioning + leadership, horizon-specific): pre-registration

Committed: 2026-11-23 (PST), before any result for the features or scores below was computed. Builds on
docs/PREREGISTRATION_V4_3_FCF.md (FCF pillar P5 and its FAIL result, which are unchanged). Nothing is fitted or tuned
after results. Owner request (Nov 23): v4.3 = v4.2 + FCF pillar + long-horizon peer and leadership features, with
momentum dominating 6-12 months and quality / FCF / valuation / peer / leadership dominating 24-60 months.

## 1. Data
Same panel, universe (top 1000 by market cap, price >= $5), month-ends, evaluation 2014-01 onward, labels and haircut /
drag as v4.2. New inputs (pipeline/lt_features.py) come only from local SEC companyfacts: first-filed values, usable 2 days
after filing, TTM sums, 550-day staleness. **Survivorship limitation (unchanged):** the price panel only contains tickers
that still have Yahoo history; delisted firms are missing, so all absolute numbers are optimistic. Comparisons are on
the same panel.

**Peer groups:** GICS is not available free. Peer group = 2-digit SIC industry among universe members at date t; if fewer
than 6 members, the G1 sector (SIC-based) is used. This is a proxy for GICS industry. True output / capacity / unit
market-share data are not available free; revenue share and capex / asset growth are used as proxies.

## 2. Features (all known at t)
Peer positioning (financials: margin, ROIC, capex and FCF items set missing):
- `share_ch` = log(rev share of peer group now / rev share 3y earlier), shares computed over peers with both revenues
- `rel_rev_g3` = rev_g3 - peer median; `rel_om` = om - peer median; `rel_roic` = roic_5y_med - peer median
- `rel_capex_g3` = 3y capex CAGR - peer median (capacity proxy); `rel_fcfm` = FCF margin - peer median
Leadership quality:
- `roic_5y_med` level, `roic_tr3` (ROIC now - 3y ago), `gm_tr3`, `gm_std5` (lower better), `om_stab` (panel, higher better)
- consistency: `rev_yoy_std` (std of 5 yoy revenue growths, lower better), `ni_var` (std of yoy net income change / revenue,
  lower better), `neg_surp` (share of last 4 years where yoy revenue growth fell >10 pts below its prior 2-year average,
  lower better)
- `dil_3y` share-count change (lower better)
- `alloc` capital allocation = (roic_5y_med - 0.08) x clip(asset_g3, -0.1, 0.3) (reinvesting at high ROIC good,
  growing assets at low ROIC bad)
- `sue` (panel earnings-surprise proxy) is the only free "revisions" proxy; analyst revisions are not available free.

## 3. Pillars (percentile ranks per date; missing -> 0.5)
P1-P4 as v4.2; P5 as V4_3_FCF.
- P6 peer positioning = universe ranks per date: 0.25 share_ch + 0.15 rel_rev_g3 + 0.15 rel_om + 0.20 rel_roic
  + 0.10 rel_capex_g3 + 0.15 rel_fcfm
- P7 leadership = within-(date, sector) ranks: 0.15 roic_5y_med + 0.10 roic_tr3 + 0.10 gm_tr3 + 0.10 (1 - gm_std5)
  + 0.10 om_stab + 0.10 (1 - rev_yoy_std) + 0.10 (1 - ni_var) + 0.10 (1 - neg_surp) + 0.05 (1 - dil_3y) + 0.10 alloc
- Psue = within-(date, sector) rank of sue.

## 4. Scores (each blend -> per-date universe percentile -> BM < 4 cap at 0.65 -> 0-100)
- `V43S` short-horizon (3, 6, 12m cells): 0.35 P4 + 0.10 Psue + 0.1375 (P1 + P2 + P3 + P5)
- `V43L` long-horizon (24-60m cells; the headline G1 Score, verdicts, Top 30): 0.15 P4 + (0.85/6)(P1+P2+P3+P5+P6+P7)
- `V43F` = the FCF-only 5th-pillar variant (V43_eq) for comparison.
v4.3 horizon score = V43S at 6 and 12m, V43L at 24, 36, 48, 60m.

## 5. Metrics
Per horizon (6-60m): rank IC, t (v4.2 `evaluate`), probability-of-beating-SPY calibration (per-decile hit rate; reported:
top-decile hit, bottom-decile hit, Spearman of decile vs hit), top-decile excess bands p10 / p50 / p90. Monthly top-30
equal-weight portfolio 2014-01 onward with 10 bps per side: CAGR, max drawdown, % months beating SPY, downside capture.

## 6. Deployment rule (owner's rule, fixed here before results)
Deploy v4.3 (horizon scores V43S / V43L, headline V43L) iff
1. top-30 CAGR(V43L) >= top-30 CAGR(V42), and
2. top-30 max drawdown(V43L) >= max drawdown(V42) (not deeper), and
3. at every horizon 6-60m, IC(v4.3 horizon score) >= IC(V42) - 0.003 (a miss of up to .003 is "tiny"; more is material).
Fallback (also fixed now): if v4.3 fails but V43F passes the same three tests, deploy V43F as "v4.3 (FCF)" for all
horizons. If neither passes, V42 stays live and nothing is deployed.

## 7. Results (appended after the run; nothing above was changed)
