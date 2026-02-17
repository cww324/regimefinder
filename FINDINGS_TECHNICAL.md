# Findings Technical Appendix

Date: 2026-02-16

## Data Coverage
- Source: Coinbase Advanced Trade, BTC-USD spot
- Candle: 5m
- Bars: ~51,771
- Range: 2025-08-20 22:55 UTC → 2026-02-16 22:55 UTC

## Hypothesis 1: Trend / Breakout Drift (ER + breakout events)
**Script:** `scripts/drift_study.py`
**Command:**
```
python -m scripts.drift_study --days 180 --timeframes 5m,15m,1h,4h,1d
```
**Notes:**
- All ER buckets negative mean forward returns across 5m/15m/1h/4h.
- Breakout events (N=12,24; buffer 0.0/0.5) negative mean forward returns.
- 1d sample sizes are small due to 180-day history.

## Hypothesis 2: VWAP z-score Mean Reversion
**Script:** `scripts/mr_drift_study.py`
**Command:**
```
python -m scripts.mr_drift_study --days 180 --timeframes 5m,1h,4h --dev-window 48
```
**Notes:**
- All z-score buckets show negative mean forward returns across 5m/1h/4h.

## Hypothesis 3: Volatility Regime (RV percentile)
**Script:** `scripts/rv_drift_study.py`
**Command:**
```
python -m scripts.rv_drift_study --days 180 --window 2000
```
**Notes:**
- RV percentile buckets negative across 5/10/20 bars.
- Low-RV and “RV rising” events negative.

## Hypothesis 4: Time-of-day / Day-of-week
**Script:** `scripts/time_effects_study.py`
**Command:**
```
python -m scripts.time_effects_study --days 180
```
**Notes:**
- All hours and days of week show negative mean forward returns.

## Hypothesis 5: Daily Drift by Prior Return
**Script:** `scripts/daily_drift_study.py`
**Command:**
```
python -m scripts.daily_drift_study --days 720
```
**Notes:**
- Uses available ~180 days (not full 720).
- All buckets negative mean returns; sample sizes small in extremes.

---

## Paper Strategy Tests (Level 1)
### Trend Breakout Baseline
**Script:** `scripts/run_paper_level1.py`
**Command:**
```
python -m scripts.run_paper_level1 --reset
python -m scripts.dashboard --days 180 --last-trades 20
```
**Notes:**
- 0% win rate in sample; avg R ~ -2.1
- Stops dominate; median bars_to_stop ~ 1
- MAE_R ~ -1.2, MFE_R ~ 0.1

### VWAP-z Mean Reversion (MR1)
**Script:** `scripts/run_paper_meanrev_level1.py`
**Command:**
```
python -m scripts.run_paper_meanrev_level1 --reset
python -m scripts.dashboard --days 180 --last-trades 20
```
**Notes:**
- 2330 trades; win rate ~9%; avg R ~ -2.8
- Stops dominate; equity decays to 0

---

## Execution Model Notes
- Level 1 fills at next bar open.
- Stop exits average ~ -2.2R due to next-open fill and gaps.

## Recorded Outputs (Latest Run)

### Drift Study (ER + Breakout) – 5m/15m/1h/4h/1d
**Note:** see `logs/` for CSV outputs if `--save` was used.

#### 5m ER drift (selected):
- <0.25: mean 5/10/20 = -0.000068 / -0.000137 / -0.000274
- 0.35–0.45: mean 5/10/20 = -0.000456 / -0.000913 / -0.001844
- >0.60: mean 5/10/20 = -0.001796 / -0.003747 / -0.008150

#### 5m Breakout drift (selected):
- N=12, buffer=0.0: mean 5/10/20 = -0.000611 / -0.001221 / -0.002409
- N=24, buffer=0.0: mean 5/10/20 = -0.000926 / -0.001832 / -0.003707

#### 1h ER drift (selected):
- <0.25: mean 5/10/20 = -0.000910 / -0.001828 / -0.003693
- 0.35–0.45: mean 5/10/20 = -0.005070 / -0.010506 / -0.019838

#### 4h ER drift (selected):
- <0.25: mean 5/10/20 = -0.004339 / -0.008389 / -0.017028
- 0.35–0.45: mean 5/10/20 = -0.018578 / -0.035011 / -0.064034

### MR Drift (VWAP z-score) – 1h/4h
#### 1h VWAP-z (selected):
- z<-2: mean 5/10/20 = -0.005952 / -0.011861 / -0.024611
- z>2:  mean 5/10/20 = -0.004732 / -0.009722 / -0.016155

#### 4h VWAP-z (selected):
- z<-2: mean 5/10/20 = -0.024255 / -0.045079 / -0.085107
- z>2:  mean 5/10/20 = -0.009317 / -0.022083 / -0.060860

### RV Drift (5m, window=2000)
- rv_low_10: mean 5/10/20 = -0.000360 / -0.000718 / -0.001434
- rv_low_20: mean 5/10/20 = -0.000216 / -0.000433 / -0.000868
- rv_low_10_rising: mean 5/10/20 = -0.000788 / -0.001571 / -0.003121

### Time Effects (5m)
- All hours: negative mean returns for 5/10/20 bars
- All days of week: negative mean returns for 5/10/20 bars

### Daily Drift (approx. 180d data)
- All prior-return buckets negative mean forward returns (1/3/5 days)

### Paper Backtests (Level 1)
#### Trend Breakout Baseline (5m)
- Trades: 28
- Win rate: 0%
- Avg R: -2.146
- MAE_R mean/median: -1.293 / -1.206
- MFE_R mean/median: 0.534 / 0.106

#### Mean-Reversion VWAP-z (MR1)
- Trades: 2330
- Win rate: 8.76%
- Avg R: -2.791
- MAE_R mean/median: -1.456 / -1.266
- MFE_R mean/median: 0.464 / 0.000

## Hypotheses H1–H10 (Batch Studies)
**Script:** `scripts/hypothesis_studies.py`
**Command:**
```
python -m scripts.hypothesis_studies --days 180 --window 2000
```

### H1 Volatility Compression → |Return|
- |return| increases with higher RV percentiles
  - 0–10% RV: mean |ret| 5/10/20 = 0.002349 / 0.004001 / 0.006762
  - 90–100% RV: mean |ret| 5/10/20 = 0.005239 / 0.008171 / 0.012585

### H2/H3 Shock Continuation vs Reversion (abs return pct)
- Effects near zero at 0.99–0.995; no strong drift.

### H4 Asymmetry (pos vs neg shocks)
- Small and inconsistent differences; not robust.

### H5 Autocorrelation
- ret autocorr lags 1–5 near zero.
- abs ret autocorr high (lag1 ~0.36), confirming volatility clustering.

### H6 Volatility Persistence
- Future RV increases with larger |return| buckets:
  - 0–50% abs ret: mean RV ~0.00103
  - 99–100% abs ret: mean RV ~0.00241

### H7 Range Dynamics
- Forward returns ~0 across buckets.
- Forward RV slightly higher in largest range buckets.

### H8 Multi-timeframe EMA Alignment (1h/4h)
- Aligned and not-aligned both negative mean returns.

### H10 Volume Effects
- Higher volume percentiles show more negative forward returns.

## H1: Volatility Compression → Expansion
Run: 2026-02-16 23:59 UTC

Command: python -m scripts.hypothesis_studies --hypothesis H1 --days 180 --window 2000

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
