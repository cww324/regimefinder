# Coordinator Plan: P01-P04 Proper Test Sequence

Last updated: 2026-02-20
Role owner for this plan file: Coordinator

## Goal

Complete a valid, artifact-backed `P01`-`P04` portfolio-construction evaluation that is suitable for Guardian audit and shortlist selection.

## Why rerun is required

- Prior `P01`-`P04` artifacts were single-ID combined runs and were heat-blocked.
- Queue notes already flag a Coder fix requirement for family-share/heat normalization.
- Latest run set must be re-executed after the Coder fix, then audited by Guardian.

## Required sequence

1. Coder
2. Executor
3. Guardian
4. Coordinator (record next action)

Do not skip role handoffs.

## Step 1: Coder prerequisites

Coder must complete and verify:
- Remove/deprecate legacy artifact-schema assumptions in validators/scripts.
- Standardize to current artifact schema for run outputs.
- Fix portfolio heat/family-share normalization so heat metrics are bounded and interpretable.
- Confirm no regression to `scripts/run_paper_portfolio.py` artifact contract in `docs/paper_portfolio_runner_spec.md`.

Expected Coder evidence:
- code diff
- brief validation notes
- any test output for heat/concentration logic

## Step 2: Executor run matrix (after Coder fix)

Mandatory preflight in same shell:

```bash
export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["RC_DB_DSN"]) as c:
    with c.cursor() as cur:
        cur.execute("select 1")
        print(cur.fetchone())
PY
```

Run `P01`-`P04` in meaningful multi-policy context (not single-ID only):

```bash
PYTHONPATH=. .venv/bin/python scripts/run_paper_portfolio.py \
  --hypothesis-ids P01,P02,P03,P04 \
  --days 180 \
  --mode combined \
  --cost-mode bps8 \
  --output-json results/paper/<timestamp>_P01_P04_combined_180d.json
```

Then confirmation window:

```bash
PYTHONPATH=. .venv/bin/python scripts/run_paper_portfolio.py \
  --hypothesis-ids P01,P02,P03,P04 \
  --days 365 \
  --mode combined \
  --cost-mode bps8 \
  --output-json results/paper/<timestamp>_P01_P04_combined_365d.json
```

Failure policy:
- On first failure, stop.
- Confirm `results/errors/<timestamp>_paper_portfolio.json`.

## Step 3: Guardian required outputs

Guardian must:
- audit new `P01`-`P04` combined artifacts
- verify schema completeness and dataset fingerprint fields
- verify heat gate calculations and thresholds
- publish audit artifact under `results/audit/`
- update derived findings with explicit artifact references

Expected outputs:
- `results/audit/audit_<timestamp>_portfolio_construction_p01_p04_combined_180d.json`
- `results/audit/audit_<timestamp>_portfolio_construction_p01_p04_combined_365d.json`
- findings updates with pass/fail rationale and cited artifact paths

## Step 4: Coordinator closeout

Coordinator records in `queue.yaml`:
- artifacts produced
- audit result for each run
- whether `P01`-`P04` shortlist is valid for next governance step

## Forward Track (After P01-P04 Completion)

If `P01`-`P04` complete and governance permits next construction cycle, open a new
portfolio-construction hypothesis track (`P05+`) for explicit regime routing:
- regime classification first (fixed rules)
- fixed strategy allowlist/weights per regime
- fixed transition/cooldown behavior

Important boundary:
- treat router logic as portfolio-construction (meta-allocation), not a normal
  single-strategy hypothesis
- no edits to frozen standalone strategy IDs; use new `P` IDs only
