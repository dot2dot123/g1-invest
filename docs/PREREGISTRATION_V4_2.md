# G1 v4.2 pre-registration

Committed: 2026-11-12 23:13 PST, before any v4.2 (or v4.1) result was computed. Supersedes the v4.1 spec (v4.1 was never
pre-registered or run; its quant test is NOT a gate). Nothing below is tuned after results.

## 1. Model under test: `V42` (parameter-free)

Panel, universe, dates and labels are identical to the v4 test (docs/PREREGISTRATION_V4.md): cache/panel_v2.parquet,
wide universe (`univ`: top 1000 by market cap, price >= $5), monthly month-ends, evaluation dates 2014-01-01 onward
(walk-forward: every input at date t uses only data known at t; nothing is fitted), labels y{h} = h-month forward return
minus SPY, h in {6,12,24,36,48,60}. Primary labels = haircut (-30% Shumway for delisted-bad) + turnover drag; raw labels
also reported.

All percentile ranks are pandas `rank(pct=True)` per date; missing -> 0.5.

- **P1 Buffett & Munger normalized**: BM = sum of the 7 existing rule points (pipeline/style.py `bm_components`,
  max 10, 10y Treasury point-in-time). Normalized BM_n = BM / 10. Pillar = per-date percentile of BM across the universe.
- **P2 Lean Magic 15**: L15 = 10 x mean(compounders, downside) pillars (pipeline/style.py `magic_pillars`, per-date
  universe ranks). Pillar = per-date percentile of L15 across the universe.
- **P3 Cyclically-adjusted value** = mean( within-(date,sector) percentile of `ey_hist_med` [5-year trailing median of
  EBIT/EV, 60 month-ends, min 24],  within-(date,sector) percentile of `fcfy_ev` [FCF/EV] ).
- **P4 Trend & defense** = mean( within-(date,sector) percentile of `mom_12_1`,  1 - universe percentile of
  `beta_down` ).
- blend = (P1+P2+P3+P4)/4; V = per-date universe percentile of blend.
- **Quality-First Gate**: if BM < 4.0 (on the 0-10 scale; BM missing cannot occur, missing rules score half points),
  V = min(V, 0.65). Score = 100 x V.

Composite `A` = the live v2 composite (pipeline/model_v4.py `a_score`), unchanged.

## 2. Turnover with hysteresis (same rule for A and V42)

For each model, per date t (2014+, chronological): pct = per-date universe percentile of the model score.
Holdings H_t = {pct > 0.85} U (H_{t-1} n {pct > 0.65}) (enter top 15%, hold until it drops below top 35%; names that
leave the universe drop out). Monthly one-way turnover tau_t = |H_t \ H_{t-1}| / |H_t|; tau = mean over t (first date
excluded). Drag on primary labels = 2 x 0.001 x tau x h (10 bps per side, h months of rebalancing).
Plain top-decile turnover is also reported for reference.

## 3. Metrics and pass rule

Per horizon: mean per-date Spearman rank IC, overlap-adjusted t = mean/sd x sqrt(n_dates/h), top-decile mean minus
bottom-decile mean (TMB), top-decile p10. Reported on primary (haircut + hysteresis drag) and raw labels.

**PASS** iff  IC(V42) > IC(A) on primary labels at >= 4 of the 6 horizons  AND  tau(V42) <= 1.2 x tau(A).
If PASS: V42 becomes the live headline score (G1 Quant Score). If FAIL: Composite A stays live; Parts 1 & 2 ship.

## 4. UI execution rules (not backtested; shown as "model estimates, not advice")

Mapping while A is live: **Quant Score** = 100 x live-score percentile (A, or V42 if it passes); **Upside** = U (0-100,
v4 sleeves); **Safety** = D (0-100). SMA40 = 40-week SMA of weekly closes (`sma40c`), EMA10 = 10-week EMA (`ema10c`),
1m return = `rev_1m`, distance from 52w high = `dd_52w`, operating-margin trend = `om_trend`.

Verdict, first match wins:
1. **CLIMAX TRIM** (held with Entry $ only): gain >= +40% AND price > 1.35 x SMA40 AND last weekly volume > 3 x median
   weekly volume (prior 52 weeks) AND weak close (last weekly close in bottom 50% of that week's high-low range).
2. **STRONG BUY**: Quant >= 75, Upside >= 70, Safety >= 60, price > SMA40, 1m return <= 15%.
3. **ACCUMULATE (Staggered)**: same fundamentals and price > SMA40 but 1m return > 15% (buy 50% now, add 50% on
   pullback to 10w/40w average).
4. **WAIT FOR TREND (Pullback)**: Quant >= 70 AND Upside >= 65 AND (price < SMA40 OR dd_52w < -0.20)
   ("Strong fundamentals; wait for price to reclaim 10w EMA or hit Deep-Value zone").
5. **SELL / BROKEN**: price < SMA40 AND (Quant < 45 OR om_trend < 0).
6. **HOLD**: everything else. Rebalance alert only when a held name's current weight (shares x price, needs shares)
   differs from its target weight (equal weight across the book's priced holdings) by more than 25% (|w/target - 1| > 0.25).

Bear Preservation (v4) adds "(buys paused)" to STRONG BUY / ACCUMULATE.

Stops: with Entry $ (CSV EntryPrice / Purchase Price, or browser-only localStorage `g1.positions.v1`): Stage 1 =
max(SMA40, P x (1 + cvar_5)); Stage 2 breakeven once gain >= +20%; Stage 3 trail at EMA10 once gain >= +40%.
Without Entry $: Initial Risk Stop = max(SMA40, P x (1 + cvar_5)), and stops are never shown above price (if the
SMA40 is above price the stop shows "below 40w avg - trend broken" and uses P x (1 + cvar_5)). For WAIT FOR TREND also
show Momentum Reclaim Trigger = EMA10 (when P < EMA10) and Deep-Value Zone = price at which EBIT/EV equals its 5y median
(EV* = EBIT / ey_hist_med; mcap* = EV* - debt + cash; P* = P x mcap*/mcap; only when EBIT > 0 and ey_hist_med > 0).

Sizing: p = calibrated 12m P(beat SPY) of the live score; base = 12m base rate; edge = max(0, p - base);
r = edge / max(sigma_down, 0.12). High Conviction if r >= 0.40 (size 6% + 2% x min(1, (r-0.40)/0.40));
Core if 0.20 <= r < 0.40 (3% + 2% x (r-0.20)/0.20); Starter if 0 < r < 0.20 (1% + 1% x r/0.20); No Edge if r = 0.
Size 0 for SELL / BROKEN and CLIMAX TRIM. Halve if WAIT FOR TREND or earnings <= 7 days. Display: "44% vs 39% usual (+5% edge)".

Volatility-managed cash banner: s = SPY downside deviation over the last 252 daily returns, annualized
(sqrt(252 x mean(min(r,0)^2))); equity = clamp(0.14 / s, 0.50, 1.00); remainder in T-Bills (SGOV). Shown alongside
the Market Weather (SPY vs 40w SMA) banner; when Bear Preservation is active the equity shown is min(vol-managed,
1 - reserve).

Dossiers: bull_case and bear_case written before f_strat (-10..+10); f_strat is an unvalidated secondary pill, never
added into the headline score. Live audit ledger: cache/live_audit.jsonl, one row per (ISO week, ticker) for book
holdings + finalists: date, ticker, quant_score, dossier_score, verdict, price; appended on each build, no cron.
