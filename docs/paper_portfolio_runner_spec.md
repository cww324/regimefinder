# Paper Portfolio Runner Spec

Purpose: define a single executable contract for paper-testing multiple `paper_candidate` hypotheses in standalone and combined modes.

## 1) Script

- Path: `scripts/run_paper_portfolio.py`
- Mode: offline paper simulation on canonical Postgres data (`RC_DB_DSN`).
- Inputs: hypothesis IDs + run window + execution mode.
- Outputs: deterministic run artifacts for Guardian audit.

## 2) CLI Contract

```bash
PYTHONPATH=. .venv/bin/python scripts/run_paper_portfolio.py \
  --hypothesis-ids H76,H77,H79,H81,H78,H82 \
  --days 180 \
  --mode standalone \
  --cost-mode bps8 \
  --output-json results/paper/<timestamp>_standalone_180d.json
```

### Required args

- `--hypothesis-ids` comma-separated list of IDs
- `--days` lookback window (`180` or `365`)
- `--mode` one of:
  - `standalone` (independent per hypothesis)
  - `combined` (single net portfolio executor)
- `--cost-mode` one of `gross|bps8|bps10`
- `--output-json` output artifact path

### Optional args

- `--dsn` Postgres DSN (fallback to `RC_DB_DSN`)
- `--timeframe` default `5m`
- `--bootstrap-iters` default `3000`
- `--seed` default `42`
- `--max-gross-exposure` default `1.0`
- `--max-asset-exposure` default `1.0`
- `--max-strategy-weight` default `0.35`
- `--cooldown-bars` default `0`
- `--daily-loss-stop-pct` default `0.03`
- `--report-csv-prefix` optional path prefix for trades/equity exports

## 3) Execution Semantics

### Standalone mode

- Run each hypothesis independently under identical execution assumptions.
- Produce per-hypothesis metrics and aggregate table.

### Combined mode

- Collect per-hypothesis signed target signals.
- Convert to normalized strategy weights.
- Aggregate to one net target position per asset.
- Enforce caps and risk controls before order simulation.

## 4) Risk/Conflict Rules (Combined)

- Netting model: opposing strategy signals offset.
- Caps:
  - gross exposure cap
  - per-asset cap
  - per-strategy weight cap
- Optional cooldown and daily loss stop.

## 5) Required Artifact Fields

- `timestamp_utc`
- `mode` (`standalone` or `combined`)
- `hypothesis_ids`
- `window_days`
- `cost_mode`
- `metrics` (summary + per-hypothesis where applicable)
- `dataset` fingerprint:
  - `start_ts`
  - `end_ts`
  - `bar_count`
  - `db_path`
  - `db_last_modified`
- `config` (risk caps, cooldown, seed, bootstrap iters)

## 6) Required Metrics

- Net return after costs
- Max drawdown
- Trade count / turnover
- Win rate / expectancy
- Monthly stability table
- Concentration stats (combined mode)
- Cross-strategy correlation matrix (combined mode)

## 7) Standard Run Plan

1. Standalone `180d` for all candidates.
2. Standalone `365d` for survivors.
3. Combined `180d` for survivor set.
4. Combined `365d` confirmation.

Each phase must be handed to Guardian before proceeding.

## 8) Failure Policy

- On run failure, write `results/errors/<timestamp>_paper_portfolio.json`.
- Exit non-zero.
- Do not claim status decisions from runner output alone.

## 9) Governance Handoff

- Executor runs the script and reports artifact paths.
- Guardian audits artifacts and updates derived outputs.
- Capital_Committee decides promotion states from audited evidence.
