# AI_AGENT.md (v2)
## Crypto Regime Trading App — Coinbase + BTC (Paper Engine → Live Bot)

> **Primary goal:** build a *truthful* system that can’t fool you (no leakage, realistic execution, strict risk).
> **Secondary goal:** once it’s proven on paper, graduate to small live size, then scale capital.
>
> This is **not HFT** and does **not** compete on microseconds. We trade **5–120 minute holds** on **5-minute candles**.

---

## 0.5) Key Decisions (Locked for Phase 0–1)

- **Direction-aware logic:** all stop/target rules must support long and short.
- **Phase 1 trading:** **long-only** (set `ALLOW_SHORTS = false`); architecture must support shorts for later.
- **VWAP definition:** **rolling VWAP** over `N = 48` bars (4 hours on 5m).
- **Exit timing consistency:** in backtest/paper, exits fill at **next bar open** unless Level 2 execution is enabled.
- **Regime switch hysteresis:** require **2 consecutive bars** in a new regime before forcing exit, or allow **1 bar** of “trend → uncertain” without exit.

## 0.6) Hypothesis Study Protocol (Locked)

- Hypothesis studies are **modular**: run **one hypothesis per execution**.
- The runner must require an explicit `--hypothesis` flag (no implicit defaults).
- Findings updates are **append-only** to:
  - `FINDINGS.md`
  - `FINDINGS_TECHNICAL.md`
- Never rewrite or delete prior findings entries from study runs.

---

## 0) Non‑Negotiables (Read this first)

- **No leakage.** Features must be computable only from information available at decision time.
- **No random train/test splits.** Use **walk‑forward** validation only.
- **No brute-force parameter hunts.** Only small, principled tuning after a baseline works.
- **No ML until plumbing is proven.** ML is Phase 3.
- **Risk before returns.** Hard daily loss caps, max trades/day, stop trading when uncertain.
- **Everything logged.** Decisions, features, regime, orders, fills, PnL, drawdown.

---

## 1) Scope

### Instrument
- **BTC-USD spot** on **Coinbase Advanced** (via Coinbase API)

### Timeframe & holding period
- Candle: **5-minute**
- Typical hold: **5–120 minutes**

### What “paper trading” means here
- **Level 1 Paper (Forward-test signals):**
  - Live data → signal → simulated fill → log PnL
  - Simple fill model (conservative)
- **Level 2 Paper (Execution-realistic):**
  - Limit-first execution simulation, spread/slippage, timeouts, partial fills, reconciliation
  - This is the version required before live trading

---

## 2) System Architecture

### 2.1 Data Layer
- Pull BTC-USD 5m candles (REST and/or websocket aggregation)
- Store in SQLite (recommended):
  - `candles_5m`
  - `features_5m`
  - `signals`
  - `paper_orders`
  - `paper_fills`
  - `equity_curve`
  - `model_registry` (later)

### 2.1.1 Data Integrity (must pass every loop)
- **Closed-bar only:** act only on fully closed 5m candles
- **Gap detection:** if expected bar missing, flag `data_gap = true` and halt trading
- **Duplicate detection:** ignore or overwrite duplicates based on timestamp primary key
- **Clock drift:** track `source_lag_seconds`; halt if lag exceeds threshold
- **Quality flags:** persist `bar_count_ok`, `data_gap`, `source_lag_seconds` in logs

### 2.2 Feature Layer (minimal strong set)
Compute each loop (every 5 minutes):

**Returns**
- `r1 = log(close/prev_close)`
- Rolling stats on returns

**Efficiency Ratio (ER) — directionality**
- Lookback `n = 20` bars (~100 minutes)
- `net = abs(close[t] - close[t-n])`
- `gross = sum(abs(close[i] - close[i-1]))`
- `ER = net / gross` in [0, 1]

**Realized Volatility (RV)**
- Rolling stdev of returns over `n = 48` bars (~4 hours)

**Optional helpers (Phase 2+)**
- VWAP (rolling, `N = 48`)
- MA slope (e.g., EMA(20) slope)
- Distance from VWAP / MA
- Range expansion (ATR or high-low)

---

## 3) Regime Definitions (Rules First)

We use a **4-regime grid**: (Trend vs Mean Reversion) × (High vs Low/Normal Vol).  
Optional 5th regime: **No Trade**.

### 3.1 Trend vs Mean Reversion (using ER)
- **Trend:** `ER >= 0.35`
- **Mean Reversion / Chop:** `ER <= 0.25`
- **Uncertain band:** `0.25 < ER < 0.35` → **no trade or reduced size**

### 3.2 Volatility regime (percentiles)
Compute RV percentile over a rolling long window (e.g., 60 days):
- **High Vol:** `RV > 70th percentile`
- **Low/Normal Vol:** otherwise
- Optional: **Ultra-high** at `> 90th percentile` → trade smaller or stand down

### 3.3 No‑Trade Filter (saves accounts)
- **No Trade:** `ER < 0.20` AND `RV > 80th percentile`

### 3.4 Final regimes
A) Trend + Low/Normal Vol  
B) Trend + High Vol  
C) Mean Reversion + Low/Normal Vol  
D) Mean Reversion + High Vol  
E) No Trade (optional)

---

## 4) Strategy Routing

- If regime ∈ {A, B} → **Trend Expert**
- If regime ∈ {C, D} → **Mean Reversion Expert**
- If regime = E or Uncertain → **No trade** (or reduce risk)

> Early build: experts are rule-based prototypes.  
> Later build: experts can be ML policies per regime.

---

## 5) Risk Management Rules

- Risk per trade: **0.5%–1.0%**
- Max daily drawdown: **3%** (hard stop)
- Max trades/day: **3**
- If state is uncertain (missing data, API errors, unknown fill status): **halt** (paper) or **flatten/halt** (live later)
- Max concurrent positions: start with **1**
- **Position sizing:** must be tied to stop distance (ATR-based), not arbitrary notional

---

## 6) Paper Engine Requirements

### Level 1 Paper Fill Model (minimum viable)
- Use conservative assumptions:
  - Buy fills at **ask**, sell fills at **bid** (or mid + half-spread proxy)
  - Apply fee model (even if “fee free,” assume costs via spread)
  - Add fixed slippage buffer (small, configurable)
- Log:
  - timestamp, regime, signal, assumed fill, pnl, equity

### Level 2 Paper Engine (execution-realistic)
- Limit-first order logic:
  - place limit near bid/ask
  - timeout after N candles; optionally cross the spread
- Track:
  - open orders
  - partial fills (if modeled)
  - cancel/replace
- Reconciliation:
  - on restart, re-load state from DB and resume safely
- **Execution timing:** if Level 2 is disabled, fills occur at **next bar open** only

**Explicit Level 2 rules (define before coding):**
- **Limit placement:** join best bid/ask or improve by one tick (configurable)
- **Timeout:** cancel after `N` candles without fill
- **Crossing:** after timeout, optionally cross spread to fill
- **Partial fills:** assume either full-fill or configurable partial ratio
- **Queue priority:** assume worst-case (fill only if price trades through limit)
- **Gaps:** if price gaps beyond limit, fill at first tradable price per model
- **Slippage model:** add fixed bps or ATR fraction on fills
- **Fees:** always apply fees even if fee tier is zero

---

## 6.5) Diagnostics (Phase 1+)

**Per-trade diagnostics (store on each trade):**
- `mae_r`, `mfe_r` (in R units)
- `bars_to_stop` (only for stop exits)
- `stop_price_used`, `exit_price_used`, `risk_per_unit`

**Stop model note:**
- Stops trigger on bar `t`, but fills at **next bar open** (Level 1).
- This can produce losses worse than -1R if price gaps.

> **Gate:** do not go live until Level 2 is stable and forward-tested.

---

## 7) ML Rules (Do not start until Phase 3)

### 7.1 What ML is allowed to do (initially)
- **Regime classifier** predicts `P(trend)` (and optionally `P(high_vol)`).
- It does **not** predict next-candle direction at first.

### 7.2 Allowed models (start simple)
- Logistic Regression
- Random Forest
- Gradient Boosting (later)

### 7.3 Validation rules (hard)
- **Walk-forward only** (rolling windows)
- Maintain a **champion/challenger**:
  - champion stays live
  - challenger trains on new data
  - promote only if it wins out-of-sample and doesn’t increase drawdown beyond cap
- Use an uncertainty band:
  - if `0.45 < P(trend) < 0.55` → no trade (or reduce size)

### 7.4 Retraining schedule
- Weekly or bi-weekly (not hourly)
- Never auto-deploy without passing gates

---

## 8) Build Plan (Phased Shipping Plan)

### Phase 0 — Plumbing Only (no strategy)
**Goal:** reliable data + DB + indicators.
- Candle ingestion loop (every 5 minutes)
- SQLite storage
- Feature computation (ER, RV)
- Unit tests / sanity checks (spot-check ER/RV against charts)

**Exit criteria:**
- Can run 24+ hours without crashing
- Features update correctly
- Restart-safe (no duplicate candles)
- **Phase 0 checklist:**
  - `candles_5m` table has continuous 5m bars (no gaps across 24h window)
  - Indicators match manual chart spot-checks
  - Data integrity flags are logged per loop
  - API error handling does not crash the loop

### Phase 1 — Level 1 Paper Trading (forward-test)
**Goal:** generate trades and log equity curve.
- Rule-based regime classification
- ONE expert strategy (**Trend first**)
- Level 1 fill model (conservative)
- Daily summary report
- Forward-test mode (incremental) with persistent state

**Exit criteria:**
- 30 days of clean paper logs
- **Max peak-to-trough drawdown <= 5%**
- **Max loss streak <= 5 trades**
- **Data quality: zero unhandled gaps, zero duplicate candles**
- No “mystery” fills or missing data
- You can explain every trade from logs

**Diagnostics required in Phase 1:**
- MAE/MFE R statistics
- Stop-exit time-to-stop histogram

### Phase 2 — Level 2 Paper Trading (execution-realistic)
**Goal:** simulate real execution behavior.
- Limit-first order simulation
- Timeouts + cancel/replace
- Slippage/spread modeling improvements
- Full state reconciliation on restart

**Exit criteria:**
- 30+ days forward test with Level 2 engine
- **Max peak-to-trough drawdown <= 6%**
- **Max loss streak <= 6 trades**
- **Slippage/fee assumptions applied on every fill**
- No state corruption during restarts

### Phase 3 — ML Regime Classifier
**Goal:** smoother/more robust regime detection than thresholds.
- Train ML to predict regime labels (from rule-based labels)
- Walk-forward validation only
- Champion/challenger promotion

**Exit criteria:**
- ML improves OOS metrics without worsening drawdown
- Uncertainty band prevents overtrading

### Phase 4 — ML Experts per Regime (optional)
**Goal:** per-regime policies.
- Train separate expert models on regime-filtered data
- Soft routing optional (probability-weighted actions)

**Exit criteria:**
- Demonstrable improvement with conservative assumptions

### Phase 5 — Small Live Deployment (later)
- Only after all gates pass
- Start tiny size, same risk caps

---

## 9) Change Control (avoid self-sabotage)
- All parameter changes require:
  - reason
  - before/after backtest
  - walk-forward comparison
  - commit message + log entry
- Never change rules mid-drawdown without evidence.

---

## 10) Definition of “Done” for MVP
MVP is done when you have:
- A stable data pipeline
- A working Level 2 paper engine
- 60+ days of forward-test logs
- A single strategy routed by regimes with controlled drawdowns
- Clear daily/weekly reports

---

## Appendix A) Exit and Stop Rules (Direction-Aware)

**ATR Stop (5m):**
- Use `ATR(14)` for adaptive sizing
- Stop distance: `1.2 * ATR`
- **Long stop:** `entry - 1.2 * ATR`
- **Short stop:** `entry + 1.2 * ATR`

**Trend Expert Take Profit:**
- Target: `2.0 * ATR`
- **Long target:** `entry + 2.0 * ATR`
- **Short target:** `entry - 2.0 * ATR`

**Mean Reversion Take Profit:**
- Target return to **rolling VWAP (N=48)**, or ATR fallback at `1.5 * ATR`
- **Long:** price below VWAP, target up to VWAP
- **Short:** price above VWAP, target down to VWAP

**Time Stop:**
- Exit after `10` candles **since entry bar close** if price fails to move in favor

**Regime Switch Exit:**
- If regime changes away from entry regime, apply hysteresis:
  - Require **2 consecutive bars** in new regime, or
  - Allow **1 bar** of “trend → uncertain” without forcing exit

**Move to Break-Even:**
- After `+1.0 * ATR` in favor, move stop to entry

---

## Appendix B) Reporting Spec (Daily)

**Required fields:**
- Date (UTC)
- Trades count, win/loss count, win rate
- Gross PnL, net PnL, fees, slippage
- Max drawdown (day and rolling)
- Avg R per trade, expectancy
- Regime exposure (% time in each regime)
- Data quality flags (gaps, lag breaches)
- Open positions at EOD (if any)

## Appendix C) Reporting Spec (Weekly)

**Required fields:**
- Week start/end dates (UTC)
- Total trades, win rate, net PnL
- Max drawdown (weekly and rolling)
- Best/worst trade (PnL and R)
- Regime performance breakdown
- Data quality summary (gaps, lag breaches)

---

## Appendix D) Phase 1 Trend Expert (Level 1)

**Signal (no lookahead):**
- Breakout level = `max(high[t-20:t])` (exclude current bar)
- Enter long when `close[t] > breakout_level + (BREAKOUT_ATR_BUFFER * ATR)`
  - Default `BREAKOUT_ATR_BUFFER = 0.2`

**Regime filter:**
- Trend only: `ER >= 0.35`

**Fill convention (Level 1):**
- Entry fill at **next bar open** + half-spread + slippage
- Exit fill at **next bar open** (same cost model)

**Cooldown:**
- After exit, wait **1 bar** before re-entry

**Logging fields:**
- `entry_time`, `entry_price`, `breakout_level`, `ER`, `ATR`, `exit_reason`

**Forward-test idempotency:**
- Persist `last_processed_candle_ts` in `bot_state`
- Use unique constraint to prevent duplicate `paper_trades` inserts

---

## Appendix E) Entry Toggles (Rule-Based)

**Breakout confirmation:**
- `BREAKOUT_ATR_BUFFER` (default `0.2`)
- `BREAKOUT_REQUIRES_CLOSE` (default `false`)

**Trend strength:**
- `ENTRY_ER_MIN` (default `0.35`)
- `ER_NO_TRADE_BAND_LOW/HIGH` (optional band)

**Volatility filter:**
- `SKIP_TOP_DECILE_RV` (default `false`)
- `RV_QUANTILE_WINDOW` (default `2000` bars, backward-looking only)

**ATR freeze (for consistent 1R):**
- `FREEZE_ATR_AT_ENTRY` (default `false`)

**Retest entry (optional):**
- `ENABLE_RETEST` (default `false`)
- `RETEST_ATR_BAND` (default `0.2`)
- `RETEST_MAX_BARS` (default `6`)

**EMA confirmation (optional):**
- `REQUIRE_EMA_CONFIRM` (default `false`)
- `EMA_FAST_PERIOD` (default `20`)
- `EMA_SLOW_PERIOD` (default `50`)
- `EMA_SLOPE_BARS` (default `3`)
- `EMA_SLOPE_MIN` (default `0.0`)

---

## Appendix F) Drift Studies (Structural)

**ER drift study:**
- Bucket ER20 and compute forward returns for `H={5,10,20}` bars.

**Breakout-event drift study:**
- Event `E_N`: `close > rolling_high(N) + buffer*ATR` for `N={12,24}` and `buffer={0.0,0.5}`
- Compute forward return stats for `H={5,10,20}`

**Stop-exit stats:**
- Track mean/median `R` on stop exits to verify fill model.

---

## Session Handoff (2026-02-17 UTC)

### Current State
- Hypothesis runner stays modular in `scripts/hypothesis_studies.py` (one hypothesis per run, required `--hypothesis`, append-only findings writes).
- Expert logic is separated into `scripts/experts/h2s_vol_expert.py` (not inside hypothesis script).
- Dashboard supports strategy filtering via `scripts/dashboard.py --strategy-name`.

### Expert Strategy (H2S-VOL Variant B)
- Filters unchanged:
  - RV percentile in `[70%, 90%)`
  - `1.5 <= |r1| / (atr14/close) < 2.5`
  - fixed horizon exits only (no stops)
- Variant B mapping:
  - negative shock (`r1 < 0`) -> SHORT
  - positive shock (`r1 > 0`) -> LONG

### New CLI Features in `scripts/experts/h2s_vol_expert.py`
- Split controls:
  - `--split-mode {none,holdout,walkforward}` (default `holdout`)
  - `--holdout-days`, optional `--is-days`
  - `--train-days`, `--test-days`, `--step-days`
- Existing controls retained:
  - `--days`, `--window`, `--horizons`, `--variant`, `--equity-csv-prefix`
- Friction controls:
  - `--fee_bps`, `--slippage_bps` (applied per side: entry + exit)

### Most Recent Results
- Holdout 80d OOS (Variant B):
  - `h=10`: mean `0.000401`, sharpe-like `0.0659`, final equity `1.0481`
  - `h=20`: mean `0.000945`, sharpe-like `0.1198`, final equity `1.1134`
- Holdout 90d OOS (Variant B):
  - `h=10`: mean `0.000594`, sharpe-like `0.0954`, final equity `1.0820`
  - `h=20`: mean `0.000995`, sharpe-like `0.1263`, final equity `1.1373`
- Walkforward (120/30/30), Variant B:
  - `h=10`: mean `-0.000357`, sharpe-like `-0.1038` (1 fold)
  - `h=20`: mean `0.000113`, sharpe-like `0.0243` (1 fold)
- Walkforward with friction (`fee_bps=2`, `slippage_bps=2`), `h=20`:
  - mean `-0.000687`, sharpe-like `-0.1471`, final equity `0.9629`
- Walkforward (90/30/30), Variant B (2 folds):
  - `h=10`: mean `0.000626`, sharpe-like `0.1187`, final equity `1.0658`
  - `h=20`: mean `0.000437`, sharpe-like `0.0613`, final equity `1.0459`
- Walkforward (90/30/30) with friction (`fee_bps=2`, `slippage_bps=2`), `h=20`:
  - mean `-0.000363`, sharpe-like `-0.0509`, final equity `0.9619`
- Walkforward matrix with friction (Variant B, baseline filters):
  - `60/15/15`: `h=10` mean `0.000097`, `h=20` mean `0.000195` (both near-flat)
  - `90/30/30`: `h=10` mean `-0.000174`, `h=20` mean `-0.000363`
  - `120/30/30`: `h=10` mean `-0.001157`, `h=20` mean `-0.000687`
- Controlled sweep (h=20, 60/15/15, friction on):
  - baseline `[rv 0.70-0.90, shock 1.5-2.5]`: mean `0.000195`
  - `[rv 0.65-0.90, shock 1.5-2.5]`: mean `-0.000182`
  - `[rv 0.70-0.95, shock 1.5-2.5]`: mean `-0.000211`
  - `[rv 0.70-0.90, shock 1.8-2.8]`: mean `0.000288` (fewer trades)
- Bootstrap uncertainty (3000 iters):
  - all tested 95% CIs for mean return overlap zero except one negative-only case (`120/30/30`, `h=10`)
  - no configuration currently passes strict friction-on acceptance criteria
- H2 track status:
  - archived as watchlist (not deployable on current 180d evidence)
  - reopen only with larger sample / replication and same acceptance gate
- Next hypothesis started (H14, non-H2):
  - `scripts/ablation.py --days 180` run
  - trend ablation variants A-G all strongly negative (`avgR` roughly `-2.86` to `-3.03`)
  - MR1 still negative (`avgR -1.88`, `2328` trades)

### Where Outputs Were Appended
- Summary notes:
  - `FINDINGS.md`
- Full technical logs:
  - `FINDINGS_TECHNICAL.md`

### Useful Resume Commands
- Holdout:
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 10,20 --split-mode holdout --holdout-days 80 --equity-csv-prefix logs/h2s_vol_expert_vb_holdout80`
- Walkforward:
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 10,20 --split-mode walkforward --train-days 120 --test-days 30 --step-days 30 --equity-csv-prefix logs/h2s_vol_expert_vb_wf`
- Walkforward with friction:
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 20 --split-mode walkforward --train-days 120 --test-days 30 --step-days 30 --fee_bps 2 --slippage_bps 2 --equity-csv-prefix logs/h2s_vol_expert_vb_wf_fee2_slip2`
- Walkforward robustness (2 folds):
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 10,20 --split-mode walkforward --train-days 90 --test-days 30 --step-days 30 --equity-csv-prefix logs/h2s_vol_expert_vb_wf_90_30_30`
- Walkforward robustness with friction:
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 20 --split-mode walkforward --train-days 90 --test-days 30 --step-days 30 --fee_bps 2 --slippage_bps 2 --equity-csv-prefix logs/h2s_vol_expert_vb_wf_90_30_30_fee2_slip2`
- Matrix run (friction-on default):
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 10,20 --split-mode walkforward --train-days 60 --test-days 15 --step-days 15 --fee_bps 2 --slippage_bps 2 --equity-csv-prefix logs/h2s_vol_expert_vb_wf_60_15_15_fee2_slip2`
- Controlled sweep example:
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 20 --split-mode walkforward --train-days 60 --test-days 15 --step-days 15 --fee_bps 2 --slippage_bps 2 --rv-pct-min 0.70 --rv-pct-max 0.90 --shock-atr-min 1.80 --shock-atr-max 2.80 --equity-csv-prefix logs/h2s_vol_expert_sweep_b_shock18_28`
- Uncertainty stats:
  - `.venv/bin/python -m scripts.h2s_vol_uncertainty --label wf_60_15_15_base --horizons 10,20 --train-days 60 --test-days 15 --step-days 15 --rv-pct-min 0.70 --rv-pct-max 0.90 --shock-atr-min 1.50 --shock-atr-max 2.50 --fee_bps 2 --slippage_bps 2 --bootstrap-iters 3000`
- H14 ablation continuation:
  - `.venv/bin/python -m scripts.ablation --days 180`

---

**End of AI_AGENT.md v3**
