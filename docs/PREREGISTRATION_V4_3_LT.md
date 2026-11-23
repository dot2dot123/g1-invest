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

Run: pipeline/lt_features.py then pipeline/model_v43lt.py (2026-11-23 AM PST, panel through 2026-11-09). Coverage of
universe rows 2014+: share_ch 78%, rel_roic 63%, roic_tr3 56%, rev_yoy_std 78%, alloc 59%.

| h | V42 IC (t) | V43F IC (t) | V43S IC (t) | V43L IC (t) | P6 alone | P7 alone | top-decile hit V42 / V43F / v4.3 | top-decile p10/p50/p90 V42 vs v4.3 |
|---|---|---|---|---|---|---|---|---|
| 3m | .031 (1.96) | .031 (1.99) | .022 (1.17) | .033 (2.13) | .015 | .033 | .451 / .451 / .450 | -.141/-.011/+.122 vs -.143/-.012/+.126 |
| 6m | .047 (2.23) | .048 (2.40) | .034 (1.34) | .049 (2.41) | .014 | .047 | .456 / .452 / .455 | -.202/-.016/+.178 vs -.209/-.017/+.183 |
| 12m | .061 (2.27) | .062 (2.45) | .043 (1.28) | .065 (2.41) | .015 | .063 | .437 / .436 / .436 | -.293/-.032/+.251 vs -.300/-.033/+.255 |
| 24m | .092 (2.83) | .093 (3.04) | .067 (1.66) | .095 (2.88) | .018 | .085 | .415 / .413 / .416 | -.409/-.059/+.329 vs -.408/-.058/+.342 |
| 36m | .116 (4.05) | .115 (4.37) | .090 (2.40) | .118 (4.06) | .029 | .098 | .394 / .391 / .402 | -.478/-.086/+.407 vs -.477/-.083/+.416 |
| 48m | .132 (4.38) | .130 (5.15) | .103 (2.33) | .135 (4.62) | .039 | .113 | .369 / .368 / .381 | -.547/-.127/+.476 vs -.545/-.116/+.520 |
| 60m | .125 (3.23) | .124 (3.64) | .092 (1.64) | .130 (3.48) | .043 | .113 | .351 / .355 / .367 | -.606/-.174/+.538 vs -.609/-.159/+.571 |

(v4.3 = V43S at 3-12m, V43L at 24-60m.) Top-30 monthly, 2014-01 to 2026-10, 10 bps/side:
V42 CAGR 10.4%, max DD -26.1%, months beating SPY 44.4%, down capture 0.83;
V43F 12.1%, -22.9%, 51.0%, 0.80; V43S 9.7%, -26.1%, 47.7%, 0.79; V43L 12.7%, -19.9%, 51.6%, 0.78 (SPY 13.9%, -23.9%).

Decision: v4.3 FAILS rule 3 (the momentum-heavy short score V43S loses .013 IC at 6m and .018 at 12m); rules 1-2 pass.
Fallback V43F PASSES (CAGR and drawdown better; IC gaps +.001/+.001/+.001/-.001/-.002/-.001, all within .003).
**Deploy V43F as "G1 v4.3 (FCF)" for all horizons.** Reported, not acted on: V43L used at every horizon would have
beaten V42's IC at all horizons and had the best top-30 result, but that configuration was not pre-registered; it is
a candidate for a new pre-registered / forward test. P7 (leadership) is the strongest new pillar on its own; P6 (peer
positioning proxies) is weak (t < 1).
