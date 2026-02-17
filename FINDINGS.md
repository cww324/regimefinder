# Findings Summary

Date: 2026-02-16
Scope: BTC-USD spot, Coinbase, 5m candles; ~180 days of history (2025-08-20 → 2026-02-16)

## Hypotheses Tested (keep updated)
1. Trend / Breakout drift via ER buckets and breakout events (5m/15m/1h/4h)
2. Mean-reversion via VWAP z-score (5m/1h/4h)
3. Volatility regime via RV percentile buckets (5m)
4. Time effects via hour-of-day and day-of-week (5m)
5. Daily drift by prior-day return bucket (daily from 5m resample)
6. Volatility compression → expansion (RV percentile vs |return|)
7. Large shock continuation/reversion (abs return percentiles)
8. Shock asymmetry (positive vs negative shocks)
9. Return autocorrelation (lags 1–5) and abs return autocorrelation
10. Volatility persistence after large |returns|
11. Range dynamics (range/ATR vs forward return/vol)
12. Multi-timeframe EMA alignment (1h/4h) vs forward returns
13. Volume spike effects (volume percentiles)

## Data Coverage
- Bars: ~51,771 (5m)
- Range: 2025-08-20 22:55 UTC → 2026-02-16 22:55 UTC
- Notes: 180 days of 5m data, backfilled via API in chunks

---

## Trend / Breakout Drift (5m/15m/1h/4h)
### ER Drift (forward returns H={5,10,20})
- All ER buckets show **negative mean returns** across 5m, 15m, 1h, and 4h.
- Higher ER does **not** improve drift; often worse at longer horizons.

### Breakout Event Drift (close > rolling high + buffer*ATR)
- Negative mean returns across N={12,24}, buffer={0.0,0.5}, H={5,10,20}.
- Hit rates often >50%, but expectancy remains negative.

**Conclusion:** No evidence of positive trend/breakout drift on 5m–4h over the last ~180 days.

---

## Mean-Reversion Drift (VWAP z-score)
### 5m VWAP-z
- All z-score buckets show **negative mean forward returns**.

### 1h and 4h VWAP-z
- Still negative mean forward returns for all z buckets.

**Conclusion:** VWAP deviation mean-reversion shows no positive drift on 5m/1h/4h.

---

## Volatility Regime Drift (RV percentile)
- RV percentile buckets (0–10%, 10–30%, 30–70%, 70–90%, 90–100%) all show **negative mean forward returns**.
- Low-RV and “RV rising from low” signals also negative.

**Conclusion:** No positive drift from RV regime filters on 5m.

---

## Time Effects (5m)
- Hour-of-day and day-of-week drift studies show **negative mean returns** across all buckets.

**Conclusion:** No structural time-of-day or day-of-week edge in BTC 5m.

---

## Volatility Compression → Expansion (RV percentile vs |return|)
- Absolute forward returns **increase with higher RV percentiles**; low-RV states do **not** show larger |returns|.
**Conclusion:** Compression → expansion hypothesis not supported on 5m.

---

## Shock Effects (Large Moves)
- Shock continuation/reversion effects are **near-zero**; no strong positive drift.
- Asymmetry: negative shocks show slightly higher positive forward means in some horizons, but still small and inconsistent.

**Conclusion:** Large-shock continuation/reversion is not a strong edge on 5m.

---

## Autocorrelation (Returns vs Abs Returns)
- Returns autocorrelation near zero (lags 1–5).
- Abs returns autocorrelation **high and persistent** (volatility clustering).

**Conclusion:** Volatility clustering is present; return predictability is not.

---

## Volatility Persistence (ARCH/GARCH style)
- Future RV increases monotonically after large |return| buckets.

**Conclusion:** Volatility persistence is real; useful for risk/regime, not direction.

---

## Range Dynamics (Range/ATR)
- Forward returns near zero across range buckets.
- Forward RV modestly higher in largest range buckets.

**Conclusion:** Range predicts volatility, not direction.

---

## Multi-Timeframe EMA Alignment
- Aligned vs not-aligned states show **negative mean returns** on 5m horizons.

**Conclusion:** No directional edge from simple EMA alignment in this window.

---

## Volume Spike Effects
- Higher volume percentiles show **more negative** forward returns.

**Conclusion:** Volume spikes do not provide positive directional drift on 5m.

---

## Daily Drift by Prior Return Bucket
- Tested prior-day return buckets (requested 720 days, but only ~180d available).
- All buckets negative mean forward returns (sample sizes small in extremes).

**Conclusion:** No obvious daily drift by prior return in this dataset.

---

## Strategy Backtests (Paper, Level 1)
### Trend Breakout (baseline)
- 0% win rate, avg R ~ -2.1
- Stops dominate (median bars_to_stop ~1)
- MAE_R ~ -1.2, MFE_R ~ 0.1

### Mean-Reversion VWAP-z (MR1)
- 2330 trades, 8.8% win rate, avg R ~ -2.8
- Stops dominate; equity decays to 0

**Conclusion:** Both baseline trend and MR1 are strongly negative under current fill model.

---

## Execution Model Notes
- Stops trigger on bar t, fills at **next bar open** (Level 1).
- Average stop exit ~ -2.2R due to next-open fill and gaps.
- This behavior is consistent with model assumptions, not a bug.

---

## Current Decision
- **Pause trend-breakout and VWAP-z mean-reversion on 5m–4h.**
- No evidence of positive drift in tested hypotheses.

---

## Next Options
1. Test higher timeframes (daily/weekly) with longer history (>1–3 years).
2. Explore non-price features (order book, funding, derivatives, on-chain).
3. Switch instruments (ETH or less efficient altcoins) and re-run the same drift pipeline.

### H1: Volatility Compression → Expansion
- Run: 2026-02-16 23:59 UTC
- Days: 180, Window: 2000

 bucket  h     mean   median      std     n
  0-10%  5 0.002349 0.000723 0.009936  5489
  0-10% 10 0.004001 0.001042 0.013992  5484
  0-10% 20 0.006762 0.001446 0.019333  5474
 10-30%  5 0.002481 0.001020 0.006177  9744
 10-30% 10 0.003986 0.001539 0.008588  9739
 10-30% 20 0.006453 0.002436 0.011926  9729
 30-70%  5 0.002521 0.001407 0.004338 19161
 30-70% 10 0.003798 0.002073 0.005872 19156
 30-70% 20 0.005830 0.003247 0.008041 19146
 70-90%  5 0.003874 0.002146 0.005741  9917
 70-90% 10 0.005940 0.003342 0.007799  9912
 70-90% 20 0.009251 0.005785 0.010164  9902
90-100%  5 0.005239 0.002811 0.008061  5009
90-100% 10 0.008171 0.004507 0.010891  5004
90-100% 20 0.012585 0.007834 0.014197  4994
