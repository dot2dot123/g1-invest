# G1 v4.2 — 3-month horizon (pre-registered 2026-11-13 15:22 America/Los_Angeles)

This document is frozen **before** any 3-month backtest is run. It does not change the live overall G1 Score, which stays V42 as decided by `docs/PREREGISTRATION_V4_2.md`.

Nothing below is financial advice. G1 is for Gary A's personal research only.

## 1. Why this test exists

The dashboard will show a compact per-horizon score strip on every row and Look Up card: 3m, 6m, 1y, 2y, 3y, 4y, 5y.

- **6m to 60m (shown as 6m, 1y, 2y, 3y, 4y, 5y):** G1-only. The existing v4.2 out-of-sample calibration at that horizon — the historical share of similar-V42 names that beat SPY — is shown as a 0–100 mini score. The headline G1 Score and the verdict rules do not change.
- **3m:** there is no 3-month model yet. This document pre-registers a 3-month evaluation of the same two scores already used at 6–60m: the v4.2 blend (V42) and the v2 composite (A). The dashboard will show **both**:
  - **G1 3m:** the better of V42 and A under the rule in §3, as a 0–100 score (universe percentile of that model, and the matching 3m calibration / historical odds when the test has been run). If the winner's overlap-adjusted *t* on rank IC is below 2, the 3m G1 cell is marked **unvalidated** with a tooltip. A non-significant result still gets shown; it does not replace the live headline score.
  - **Danelfin 3m:** Danelfin's AI Score (their published 3-month view, 1–10) from cached / uploaded data first. The API is used only for book holdings that are still missing a score, at most ~100 calls, and stops on any quota or upgrade prompt. If no data: the Danelfin slot shows **n/a / No Danelfin data**. Nothing is substituted into the Danelfin slot.
- **6m to 5y stay G1-only** (no Danelfin scores in those slots).

Each portfolio tab also reports an **agreement rate**: the share of names with both scores where G1 3m and Danelfin 3m are in the same half (both top half or both bottom half). G1 3m top half = chosen-model universe percentile ≥ 50. Danelfin 3m top half = AI Score ≥ 6. Names missing either score are left out of the rate.

## 2. Scores under test (unchanged definitions)

Both scores are the same functions already frozen for longer horizons. No new features, no fitted parameters, no peeking at 3-month labels to change the score.

- **V42** = `pipeline/model_v42.py` `v42_score`: equal blend of universe-percentile Buffett & Munger, universe-percentile lean Magic 15, mean within-sector percentile of `ey_hist_med` and `fcfy_ev`, and mean of within-sector `mom_12_1` with 1 − universe percentile of `beta_down`; then percentile of the blend; cap at the 65th percentile when B&M < 4. Score is 0–100.
- **A** = `pipeline/model_v4.py` `a_score` (v2 composite: quality, value, low dilution, balance sheet; within-sector ranks).

Universe, walk-forward window and label construction match v4.2 except for the horizon length:

- Wide top-1000 point-in-time panel (`cache/panel_v2.parquet`), evaluation dates 2014-01 onward.
- 3-month forward excess vs SPY: \(y_3 = (1+r_{\text{stock}})/(1+r_{\text{SPY}})-1\) from month-end *t* to *t*+3 months, using the same `fwd_excess` / sit-in-SPY rule as `pipeline/features.py`. The 3-month label is added for this test only; `HORIZONS` in `pipeline/common.py` stays [6, 12, 24, 36, 48, 60].
- Shumway haircut: if the name is truly delisted before *t*+3 months and the last row has `dd_52w < -0.5` or `roa < 0`, \(y_{h3} = 0.7(1+y_3)-1\). Otherwise \(y_{h3} = y_3\).
- Primary labels = haircut + turnover drag. Drag = \(2 \times 10\,\text{bps} \times \tau \times 3\), where \(\tau\) is that model's hysteresis turnover (enter top 15%, hold until it drops below top 35%), same rule as v4.2. Raw (no haircut, no drag) labels are reported too, not used for the decision.

## 3. Decision rule (frozen)

Let IC(m) and t(m) be the overlap-adjusted rank IC and *t* of model *m* on the **primary** 3-month labels (same `evaluate()` as v4.2, with *h* = 3).

1. **Winner** = V42 if IC(V42) > IC(A), else A. Ties go to V42 (it is the live headline model).
2. The 3-month G1 cell shows that winner's current-universe percentile (0–100) and, once built, its 3-month calibration (historical odds of beating SPY, 0–100) in the strip, consistent with the 6m–5y cells.
3. If t(winner) < 2, the cell is marked **unvalidated** and the tooltip says the 3-month ranking did not reach t ≥ 2. The number is still shown.
4. This test **cannot** change the live headline G1 Score, verdicts, stops, or sizes. Those stay on V42 / the existing UI rules.

No other candidate (S_quant, S_price, a new blend, a fitted 3-month model) is in this comparison. S_price names without fundamentals show "–" in the G1 3m slot if no 3-month calibration exists for the price-only model.

## 4. What will be written after the run

Results are appended below this line (and in `cache/model_v42_3m_results.json`, gitignored). This section above will not be edited after the run. The winner, ICs, *t*, TMB, p10, turnover, and the unvalidated flag are recorded.

## 5. Results (appended after the run; nothing above was changed)

Run: `pipeline/model_v42_3m.py`, after this document was committed as `d154326` (2026-11-13 15:21 America/Los_Angeles). Evaluation dates 2014-01 onward, 151 month-ends, wide universe. Primary = haircut + hysteresis drag labels.

| model | IC (t) | TMB | top-decile p10 | hysteresis turnover |
|---|---|---|---|---|
| V42 | .031 (1.96) | +.002 | -.134 | .031 |
| A | .023 (2.05) | +.008 | -.151 | .048 |

Raw labels: IC identical (the haircut does not move the rank IC here); raw TMB V42 +.002 / A +.008.

**Winner: V42** (higher primary rank IC: .031 > .023). **unvalidated: yes** (t(V42) = 1.96 < 2). A's *t* is 2.05, but A is not the winner under the frozen IC rule. The live headline G1 Score is unchanged (still V42 from the 6–60m test). The 3-month G1 cell uses V42 and is marked unvalidated.
