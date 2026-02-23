# AI_AGENT.md (compact handoff)
## Regime Crypto Bot — Current Operating Brief

Last Updated: 2026-02-19 UTC (H86-H100 batch + paper-candidate promotion cycle completed)

## 1) Mission
- Run strict, no-tuning hypothesis research and validate only with fixed OOS protocols.
- Keep winners frozen; move forward via new baseline hypotheses or pure replication.
- Active live execution track is frozen H32 paper trading.

## 2) Canonical Files (Current Policy)
1. `FINDINGS_SIMPLIFIED.md` (primary decision log)
2. `FINDINGS_TECHNICAL.md` (commands, fold tables, CIs, reproducibility)
3. `AI_AGENT.md` (this operating brief)

Strategic guidance documents (read before starting new research cycles):
4. `RESEARCH_ROADMAP.md` — new signal families, ML-assisted hypothesis generation, data extension priorities, H114+ roadmap
5. `VALIDATION_IMPROVEMENTS.md` — gaps in current validation framework (FDR correction, permutation test, Sharpe gate, MAE gate, trade independence fix, hold-out OOS)
6. `PERFORMANCE_OPTIMIZATION.md` — pipeline bottlenecks and fixes (vectorize pct_rank_last, single-process multi-mode, parallelization)

Note:
- `FINDINGS.md` is treated as legacy/archive for now (do not require new updates there).
- Before running H114+, read `RESEARCH_ROADMAP.md` for signal family guidance.
- Before accepting a PASS classification, check `VALIDATION_IMPROVEMENTS.md` for gates not yet implemented.

## 3) Data/Environment
- Primary data: Coinbase 5m candles, BTC + ETH.
- Canonical data store:
  - Postgres `rc.*` schema (multi-asset canonical store)
- Legacy SQLite market DBs are deprecated and must not be used for active Phase 3 execution.
- Typical window in current findings: 365 days (~105k 5m bars) as of 2026-02-22.

## 4) Frozen Research Protocol (Hard Guardrails)
- No tuning.
- No new thresholds unless declared as a new hypothesis ID.
- No stacking/slicing after-the-fact.
- One focused hypothesis run at a time.
- Standard validation for trading hypotheses:
  - baseline gross / 8 bps / 10 bps
  - WF `60/15/15`
  - bootstrap CI + `P(mean>0)`
- Immediate freeze decision per hypothesis:
  - `PASS`, `BORDERLINE`, `FAIL`, or `INCONCLUSIVE`.

## 5) Current Locked Context
- H15: frozen (no tuning)
- H18: frozen (no tuning)
- H19: locked `PASS gross / FAIL at 8 bps` (rules frozen)
- H27: `FAIL` (frozen)
- H28: `FAIL` (frozen)
- H29: `FAIL` (frozen)
- H30: `FAIL` (frozen)
- H31: stats-only mapping logged
- H32: **RECLASSIFIED FAIL on 365d (2026-02-23)**
  - 180d result: `PASS gross / PASS 8 bps / PASS 10 bps`
  - 365d rerun: `PASS gross` (WF 12/14, P>0=1.000) but `FAIL bps8` (mean≈0, WF 8/14, P>0=0.54)
  - Signal is real but per-trade edge (+0.074%) cannot absorb 8bps at current frequency
  - Paper trading: UNDER REVIEW — signal exists, execution efficiency is the problem
- H33 (symmetry): **RECLASSIFIED FAIL on 365d (2026-02-23)**
  - 180d result: `PASS gross / PASS 8 / PASS 10`
  - 365d rerun: gross WF 2/14, P>0=0.000 — short side only worked in narrow 180d window
  - FROZEN as FAIL. Do not use.
- H32+H33 portfolio: **UNDER REVIEW** — H33 dead, H32 cost-constrained
- H34: `PASS gross / BORDERLINE 8 / FAIL 10` (frozen)
- H35: stats-only decile maps logged (no trading logic)
- H36: `PASS gross / BORDERLINE 8 / FAIL 10` (frozen)

Next unused hypothesis ID: H124 (available). H101-H113, H121-H123 all completed.

## 5b) Phase 2 Results (Replication-Only Additions)
- H37-H56: mostly `FAIL`; H39 is the primary `PASS`.
- H59/H60: `PASS gross / PASS 8 bps / PASS 10 bps`, frozen.
- H61: `PASS gross / PASS 8 bps / BORDERLINE 10 bps`, frozen realism variant.
- H63/H65 (horizon=8): current top candidates.
- H76/H77: next-bar execution realism replications passed.
- H78/H79: extra-cost stress remained positive through 15 bps.
- UTC window replication: 00:00-08:00 is weaker; 08:00-24:00 is strongest.
- Implementation note: generic family routing is active via `scripts/research_family_runner.py` with family dispatch in `scripts/run_hypothesis_batch.py`.

## 5c) Latest Governance Outcomes (2026-02-19)
- H86-H90 (standard batch): `H86 FAIL`, `H87 INCONCLUSIVE`, `H88 FAIL`, `H89 FAIL`, `H90 FAIL`.
- H91-H100 (batch): `H91 INCONCLUSIVE`, `H92 FAIL`, `H93 FAIL`, `H94 FAIL`, `H95 BORDERLINE`, `H96 INCONCLUSIVE`, `H97 INCONCLUSIVE`, `H98 FAIL`, `H99 INCONCLUSIVE`, `H100 FAIL`.
- Capital_Committee re-review completed after integrity reruns:
  - `H76`, `H77`, `H79`, `H81`, `H78`, `H82` promoted to `paper_candidate`.
- Paper protocol docs added for upcoming stage:
  - `docs/paper_portfolio_protocol.md`
  - `docs/paper_portfolio_executor_checklist.md`
  - `docs/paper_portfolio_runner_spec.md`

## 5d) Funding Regime Family + Infrastructure (2026-02-22)
- Data extended: OHLCV now 365 days (2025-02-22 → 2026-02-22), ~105k bars per symbol.
- Derivatives infrastructure built and running:
  - Source: Hyperliquid public API (1h funding, US-accessible, no auth). Bybit geo-blocks US IPs.
  - Tables: `rc.funding_rates`, `rc.open_interest`, `rc.liquidations` (see `db/schema.sql`)
  - Seed: `hyperliquid` venue + `1h` timeframe + `BTC`/`ETH` symbols (see `db/seed.sql`)
  - Backfill: `make backfill-derivatives` — fetches 365d Hyperliquid funding, idempotent
  - Loader: `app/db/derivatives.py` — `load_funding_rates_last_days()`, `compute_funding_features()`
  - Runner: `load_frame()` in `research_family_runner.py` now merges funding via `merge_asof` (when `--dsn` set)
  - Family: `funding_regime` added to `SUPPORTED_FAMILIES` and `build_signal()` routing
- H101-H113 (volatility_state, efficiency_mean_reversion, cross_asset_divergence, range_structure): all FAIL or INCONCLUSIVE (see FINDINGS_SIMPLIFIED.md).
- H121-H123 (funding_regime family):
  - `H121 FAIL` — extreme funding long fade; 70 trades/365d, WF 3/11 folds positive, inconsistent.
  - `H122 FAIL` — funding sign flip momentum; negative gross, clean failure.
  - `H123 FAIL` on cost gate — gross P>0=1.000, WF 12/14 folds positive (signal is real), but ~7 trades/day × 8bps cost exceeds +0.065% gross edge per trade.
- **Next hypothesis: H124** — H123 logic with tighter spread threshold (≥0.97/≤0.03) targeting 1-2 trades/day to absorb 8bps friction.

## 6) Live Paper Runner Status
- Script: `scripts/run_paper_h32_live.py`
- Purpose: frozen H32 live paper execution.
- Current behavior:
  - Ingests BTC and ETH bars (`--ingest`)
  - Recomputes ETH 1h EMA20 slope each cycle from latest bars
  - Persists `latest_btc_ts` and `latest_eth_ts` in `bot_state` key (default `h32_live_state`)
  - Blocks new signal entries if ETH is stale by more than 1 bar (>300s lag)
  - Logs ETH ingest failure warnings
  - Enforces 1-position-at-a-time; logs signals/trades/daily summaries

## 7) Critical Commands
- Preferred Postgres-safe batch execution (single-shell mode):
  - `scripts/run_batch_pg.sh`
- Mandatory DB preflight (same shell, immediately before DB-dependent runs):
  - `export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'`
  - `.venv/bin/python - <<'PY'`
  - `import os, psycopg`
  - `with psycopg.connect(os.environ["RC_DB_DSN"]) as c:`
  - `    with c.cursor() as cur:`
  - `        cur.execute("select 1")`
  - `        print(cur.fetchone())`
  - `PY`
- Start live paper runner:
  - `PYTHONPATH=. .venv/bin/python scripts/run_paper_h32_live.py --ingest`
- Verbose live monitoring:
  - `PYTHONPATH=. .venv/bin/python scripts/run_paper_h32_live.py --ingest --verbose --poll-seconds 30`
- Replay verification:
  - `PYTHONPATH=. .venv/bin/python scripts/run_paper_h32_live.py --replay-mode --replay-days 30 --replay-tolerance-bars 1`
- Paper portfolio stage references (use only when paper protocol is active):
  - `docs/paper_portfolio_protocol.md`
  - `docs/paper_portfolio_executor_checklist.md`

## 8) Logging Rules
- For each new hypothesis run, append:
  - one concise decision entry to `FINDINGS_SIMPLIFIED.md`
  - full reproducibility block to `FINDINGS_TECHNICAL.md`
- Must include:
  - exact command
  - sample size `n`
  - fold means
  - positive fold %
  - aggregated mean
  - bootstrap CI and `P(mean>0)`
  - final freeze classification

## 9) Context Hygiene Rule
- Every ~5 hypothesis runs:
  1. Start a fresh chat (`/new`)
  2. Read `AI_AGENT.md`
  3. Tail latest sections of `FINDINGS_SIMPLIFIED.md` and `FINDINGS_TECHNICAL.md`
  4. Resume from lock state without changing frozen rules

## 10) Unattended Batch Ops
- To run a batch unattended:
  - `tmux new -s research`
  - `scripts/run_batch_pg.sh`
  - Detach from tmux.
- After each batch in Codex CLI:
  1. Use `/new`
  2. Read `AI_AGENT.md`
  3. Tail `FINDINGS_SIMPLIFIED.md` and `FINDINGS_TECHNICAL.md`
  4. Read `results/summary.json`
  5. Run `scripts/run_batch_pg.sh` again
- Do not change frozen hypotheses during unattended batch execution.

## 11) Postgres RC Migration Status (Resume Here)
- Scope completed in code:
  - `db/schema.sql` and `db/seed.sql` are prepared.
  - Backfill pipeline now targets Postgres: `scripts/backfill_5m.py --dsn ...` (BTC+ETH by default).
  - Feature pipeline supports Postgres: `scripts/compute_features.py --dsn ...`.
  - Batch/research runners support Postgres via `--dsn`; `scripts/run_hypothesis_batch.py` auto-passes DSN from `RC_DB_DSN`.
  - Sanity compare script exists: `scripts/sanity_compare_legacy_vs_rc.py`.
  - Dashboard/health/report/audit scripts have optional `--dsn` support.
  - Signal snapshot support added:
    - table: `rc.paper_signal_snapshots`
    - capture script: `scripts/capture_paper_signal_snapshots.py`
- Executed in this repo session (2026-02-19 UTC):
  - Docker Postgres started: container `rc-postgres` (`postgres:16`) on `localhost:5432`.
  - DB/user created via container env:
    - `POSTGRES_DB=regime_crypto`
    - `POSTGRES_USER=rc_user`
  - Schema applied: `db/schema.sql`.
  - Seed applied: `db/seed.sql`.
  - Backfill completed: `scripts/backfill_5m.py --days 180`.
    - `rc.ingest_runs`: 1 successful run.
    - `rc.candles`: 103,543 total rows.
  - Feature compute completed:
    - BTC: 206,892 feature writes.
    - ETH: 206,896 feature writes.
    - `rc.features`: 413,788 total rows.
  - DSN configured in local `.env`:
    - `RC_DB_DSN="postgresql://rc_user:wemyss@localhost:5432/regime_crypto"`
  - Runtime requirement:
    - Execute DSN precheck and `scripts/run_batch_pg.sh` in the same shell/session.

## 12) First-Run Commands After DB Creation
Status: completed once in this repo session. Re-run only if rebuilding DB.

1. Ensure container is running (Docker path used in this repo):
   - `docker start rc-postgres`
2. Ensure DSN is set (already stored in `.env`):
   - `export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'`
3. Apply schema:
   - `docker exec -i rc-postgres psql -U rc_user -d regime_crypto < db/schema.sql`
4. Seed venue/timeframe/symbols:
   - `make db-seed`
5. Backfill candles:
   - `PYTHONPATH=. .venv/bin/python scripts/backfill_5m.py --dsn "$RC_DB_DSN" --days 180`
6. Compute features:
   - `PYTHONPATH=. .venv/bin/python scripts/compute_features.py --dsn "$RC_DB_DSN" --symbol BTC-USD --days 365`
   - `PYTHONPATH=. .venv/bin/python scripts/compute_features.py --dsn "$RC_DB_DSN" --symbol ETH-USD --days 365`
7. Optional rc sanity check (Postgres scope):
   - `PYTHONPATH=. .venv/bin/python scripts/health_report.py --dsn "$RC_DB_DSN" --days 30`
8. Batch runs against Postgres source:
   - `scripts/run_batch_pg.sh`
