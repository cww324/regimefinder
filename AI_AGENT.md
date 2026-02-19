# AI_AGENT.md (compact handoff)
## Regime Crypto Bot — Current Operating Brief

Last Updated: 2026-02-18 UTC (Postgres rc migration handoff added)

## 1) Mission
- Run strict, no-tuning hypothesis research and validate only with fixed OOS protocols.
- Keep winners frozen; move forward via new baseline hypotheses or pure replication.
- Active live execution track is frozen H32 paper trading.

## 2) Canonical Files (Current Policy)
1. `FINDINGS_SIMPLIFIED.md` (primary decision log)
2. `FINDINGS_TECHNICAL.md` (commands, fold tables, CIs, reproducibility)
3. `AI_AGENT.md` (this operating brief)

Note:
- `FINDINGS.md` is treated as legacy/archive for now (do not require new updates there).

## 3) Data/Environment
- Primary data: Coinbase 5m candles, BTC + ETH.
- Active migration target:
  - Postgres `rc.*` schema (multi-asset canonical store)
- Legacy DBs (read-only sanity reference only):
  - `data/market.sqlite`
  - `data/market_eth.sqlite`
- Typical window in current findings: ~180 days (~51k 5m bars).

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
- H32: frozen core candidate
  - Baseline: `PASS gross`, `PASS 8 bps`, `PASS 10 bps`
  - Replication interpretation: `PASS gross`, `BORDERLINE 8 bps`, `FAIL/NOT-ROBUST 10 bps`
- H33 (symmetry): frozen `PASS gross / PASS 8 / PASS 10`
- H32+H33 portfolio: frozen `PASS gross / PASS 8 / PASS 10`
- H34: `PASS gross / BORDERLINE 8 / FAIL 10` (frozen)
- H35: stats-only decile maps logged (no trading logic)
- H36: `PASS gross / BORDERLINE 8 / FAIL 10` (frozen)

Next unused hypothesis ID after H85: H86 (available).

## 5b) Phase 2 Results (Replication-Only Additions)
- H37-H56: mostly `FAIL`; H39 is the primary `PASS`.
- H59/H60: `PASS gross / PASS 8 bps / PASS 10 bps`, frozen.
- H61: `PASS gross / PASS 8 bps / BORDERLINE 10 bps`, frozen realism variant.
- H63/H65 (horizon=8): current top candidates.
- H76/H77: next-bar execution realism replications passed.
- H78/H79: extra-cost stress remained positive through 15 bps.
- UTC window replication: 00:00-08:00 is weaker; 08:00-24:00 is strongest.
- Implementation note: generic family routing is active via `scripts/research_family_runner.py` with family dispatch in `scripts/run_hypothesis_batch.py`.

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
- Start live paper runner:
  - `PYTHONPATH=. .venv/bin/python scripts/run_paper_h32_live.py --ingest`
- Verbose live monitoring:
  - `PYTHONPATH=. .venv/bin/python scripts/run_paper_h32_live.py --ingest --verbose --poll-seconds 30`
- Replay verification:
  - `PYTHONPATH=. .venv/bin/python scripts/run_paper_h32_live.py --replay-mode --replay-days 30 --replay-tolerance-bars 1`

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
  - `make batch`
  - Detach from tmux.
- After each batch in Codex CLI:
  1. Use `/new`
  2. Read `AI_AGENT.md`
  3. Tail `FINDINGS_SIMPLIFIED.md` and `FINDINGS_TECHNICAL.md`
  4. Read `results/summary.json`
  5. Run `make batch` again
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
- Not yet executed in this repo session:
  - Create live Postgres DB and apply schema.
  - Seed reference rows.
  - Backfill candles into `rc.candles`.

## 12) First-Run Commands After DB Creation
1. Export DSN:
   - `export RC_DB_DSN='postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require'`
2. Apply schema:
   - `psql "$RC_DB_DSN" -f db/schema.sql`
3. Seed venue/timeframe/symbols:
   - `make db-seed`
4. Backfill candles:
   - `PYTHONPATH=. .venv/bin/python scripts/backfill_5m.py --dsn "$RC_DB_DSN" --days 180`
5. Compute features:
   - `PYTHONPATH=. .venv/bin/python scripts/compute_features.py --dsn "$RC_DB_DSN" --symbol BTC-USD --days 365`
   - `PYTHONPATH=. .venv/bin/python scripts/compute_features.py --dsn "$RC_DB_DSN" --symbol ETH-USD --days 365`
6. Sanity check overlap vs legacy:
   - `PYTHONPATH=. .venv/bin/python scripts/sanity_compare_legacy_vs_rc.py --dsn "$RC_DB_DSN" --days 30`
7. Batch runs against Postgres source:
   - `make batch`
