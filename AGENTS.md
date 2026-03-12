# AGENTS.md
Regime Crypto Research Governance Constitution (Phase 3)
Last Updated: 2026-03-11

---------------------------------------------------------------------

# 0) PURPOSE

This document defines the research governance rules for the Regime Crypto
hypothesis pipeline.

It exists to:
- Prevent overfitting / parameter mining / emotional iteration
- Eliminate status drift and conflicting PASS/FAIL claims
- Enforce artifact-backed, reproducible decisions
- Enable safe multi-agent execution via `queue.yaml` batching

No session may proceed without reading this file.

---------------------------------------------------------------------

# 1) PRECEDENCE + MANDATORY STARTUP READ ORDER

Precedence rule:
- If instructions conflict across docs, `AGENTS.md` takes precedence.

Before any action:

1. Read `AGENTS.md`
2. Read `OPERATING_BRIEF_v3.md` (supersedes `AI_AGENT.md`)
3. Read `results/summary.json` (if it exists)
4. Tail latest section of `FINDINGS_365D.md`

If `results/summary.json` does not exist, Guardian must generate it from
run artifacts before any promotions or freeze claims are made.

---------------------------------------------------------------------

# 2) ROLE DECLARATION REQUIREMENT

Every session must explicitly declare exactly one role:

- Coordinator
- Architect
- Coder
- Executor
- Guardian
- Capital_Committee

No agent may perform two roles on the same hypothesis in the same session.
Across sessions, role changes are allowed only after context reset and
explicit new role declaration.

---------------------------------------------------------------------

# 3) SOURCE OF TRUTH POLICY

Canonical truth = `results/runs/*.json` artifacts.

- `results/summary.json` must be built from artifacts only.
- Summary build must be deterministic and idempotent (same artifacts -> byte-identical summary output).
- Findings files are derived documents and not authoritative.
- Manual PASS/FAIL statements are invalid unless backed by a run artifact.

---------------------------------------------------------------------

# 4) DETERMINISTIC CLASSIFICATION POLICY

Classification for TRADEABLE hypotheses is derived from artifact metrics only.

Inputs (cost-mode specific):
- baseline mean / CI / `P(mean>0)`
- walkforward aggregate mean / CI / `P(mean>0)`
- walkforward positive fold %

Default operational interpretation:
- `PASS`: positive mean with CI lower bound > 0 and stable fold support.
- `BORDERLINE`: positive mean but CI crosses 0 and/or weaker fold support.
- `FAIL`: non-positive edge after required costs or unstable negative profile.
- `INCONCLUSIVE`: insufficient sample/folds for confident classification.

Fold-support defaults (governance-level):
- Preferred fold regime: 7-8 folds when standard WF geometry permits.
- `PASS` requires: positive_fold_pct >= 60% and fold_count >= 7.
- `BORDERLINE`: positive_fold_pct in [50%, 60%), or fold_count in [5, 7) with otherwise positive profile.
- `FAIL`: positive_fold_pct < 50%, or clearly negative/unstable post-cost profile.

Sample-size defaults (governance-level):
- `INCONCLUSIVE` if baseline trade count `n < 50`.
- `INCONCLUSIVE` if `fold_count < 5`.

INCONCLUSIVE handling policy (no silent loops):
- `inconclusive_insufficient_sample` (`n < 50` and/or `fold_count < 5`):
  - eligible for one re-queue after explicit data expansion (for example longer window/backfill).
- `inconclusive_data_constraint` (coverage/fingerprint or infrastructure limitation):
  - hold until constraint is fixed, then one rerun allowed with same ID/rules.
- `inconclusive_weak_signal` (enough sample/folds but unstable edge):
  - archive by default; further exploration requires a NEW hypothesis ID.
- Any second INCONCLUSIVE with the same reason category must be archived unless
  Coordinator records an explicit governance exception in `queue.yaml` notes.

Nuance rule:
- If a hypothesis uses a constrained window that cannot produce 7+ folds,
  Guardian must apply the fallback above (`fold_count >= 5`) and mark the decision
  as reduced-confidence in Findings.

Guardian is responsible for consistent application and for recording the
artifact IDs used for each classification in derived logs.

---------------------------------------------------------------------

# 5) AGENT ROLES & PERMISSIONS

--------------------------------------------------
ROLE: Coordinator (Overseer / Project Manager)
--------------------------------------------------

Purpose:
Keep Phase 3 organized and prevent drift in what runs next.

Allowed:
- Edit operational planning docs only (for example: checklists, notes)
- Own and edit `queue.yaml` (queue ordering, next_index, paused, notes)
- Assign the next batch (max 10) and track completion status

Forbidden:
- Editing `hypotheses.yaml`
- Editing strategy logic or code
- Running backtests
- Writing PASS/FAIL classifications
- Promoting strategies

Outputs:
- Updated `queue.yaml`
- Checklist progress notes

--------------------------------------------------
ROLE: Architect (Hypothesis Author)
--------------------------------------------------

Purpose:
Define NEW hypotheses as new IDs only.

Allowed:
- Add NEW hypothesis IDs in `hypotheses.yaml` (for example: `H86+`)
- Write clear hypothesis blocks with:
  WHY / RULES / PARAMETERS / FAILURE CONDITIONS / EXPECTED FAILURE MODE

Forbidden:
- Running backtests
- Viewing performance results before rules are frozen
- Editing frozen hypotheses (any existing ID classified frozen)
- Changing thresholds/filters of existing hypotheses
- Post-hoc slicing/stacking without a new ID

Outputs:
- YAML diff adding new IDs only (no edits to existing IDs)

--------------------------------------------------
ROLE: Coder (Implementation Engineer)
--------------------------------------------------

Purpose:
Implement and maintain research tooling without changing hypothesis intent or governance outcomes.

Allowed:
- Edit code/scripts required for execution tooling (for example: `scripts/*.py`)
- Add or update supporting tests for tooling behavior
- Add/update implementation-facing docs tied to tooling usage
- Fix bugs in runners and operational utilities used by Executor/Guardian

Forbidden:
- Editing `hypotheses.yaml` strategy rule definitions
- Running backtests or paper test campaigns
- Editing `queue.yaml`
- Writing PASS/FAIL classifications, freezes, or promotions
- Editing `results/summary.json`, `results/audit/*`, or derived findings status claims

Outputs:
- Code diffs for tooling implementation
- Optional test diffs and implementation notes

--------------------------------------------------
ROLE: Executor (Backtest Operator)
--------------------------------------------------

Purpose:
Run hypotheses exactly as defined, using the queue.

Allowed:
- Run the batch runner (for example: `scripts/run_hypothesis_batch.py`)
- Postgres safety preference: run `scripts/run_batch_pg.sh` (single-shell DSN + probe + batch)
- Direct `make batch` is allowed when environment is already verified in the same shell
- Run exactly the next batch of size `queue.yaml:batch_size` (default 10)
- Produce append-only artifacts under `results/runs/`

Forbidden:
- Editing `queue.yaml`
- Editing `hypotheses.yaml`
- Editing findings files
- Re-running modified variants without a new hypothesis ID
- Manual classification outside artifacts

Outputs:
- Append-only run artifacts under `results/runs/`
- If any run fails: `results/errors/<timestamp>_<hyp>.json` and STOP batch

--------------------------------------------------
ROLE: Guardian (Integrity, Audit, and Summary Builder)
--------------------------------------------------

Purpose:
Enforce integrity and ensure all statuses are artifact-backed.

Allowed:
- Validate artifact schema and completeness
- Verify dataset fingerprints and no silent data drift
- Confirm friction tiers applied (gross / bps8 / bps10)
- Confirm WF 60/15/15 present
- Confirm bootstrap CI + P(mean>0) present
- Rebuild `results/summary.json` from artifacts only
- Update Findings files as derived outputs from summary/artifacts

Forbidden:
- Editing hypothesis logic
- Running exploratory variants
- Creating new hypotheses
- Promoting strategies to paper/live

Outputs:
- Audit report (recommended: `results/audit/audit_<timestamp>.json`)
- Deterministic `results/summary.json`
- Derived updates to `FINDINGS_SIMPLIFIED.md` / `FINDINGS_TECHNICAL.md`

Write authority:
- Guardian is the only role allowed to write:
  - `results/summary.json`
  - `results/audit/*`
  - derived status lines in Findings files

--------------------------------------------------
ROLE: Capital_Committee (Promotion Authority)
--------------------------------------------------

Purpose:
Approve promotion to paper/live based on validated evidence.

Allowed:
- Promote strategy status to:
  - candidate
  - frozen_pass
  - paper_candidate
  - live_candidate

Promotion conditions required:
- Hypothesis rules are frozen (no tuning allowed)
- Guardian audit passes integrity checks
- Passed friction tiers as required (gross / bps8 / bps10)
- Passed WF 60/15/15 and bootstrap CI + P(mean>0)
- Meets stability/coverage minimums (trade density, fold stability)

Forbidden:
- Requesting parameter changes
- Suggesting just one tweak
- Running tests
- Editing YAML/code/findings
- Editing `results/summary.json` or `results/audit/*`

Outputs:
- Promotion decision log entry in `results/decisions/promotion_<timestamp>.md`

---------------------------------------------------------------------

# 6) FREEZE AUTHORITY RULE (TWO-KEY SYSTEM)

A hypothesis may be declared frozen only if:

1) Executor produced a run artifact under `results/runs/`
2) Guardian validated the artifact and rebuilt `results/summary.json`
3) The freeze classification is derived from summary/artifacts (not memory)

No single role may both run and freeze.

Frozen means:
- No parameter changes
- No threshold changes
- No post-hoc slicing/stacking
- Any modification requires a NEW hypothesis ID

---------------------------------------------------------------------

# 7) HYPOTHESIS DEFINITION RULE (NO POINTER-ONLY DEFINITIONS)

All TRADEABLE hypotheses must have canonical rule definitions in
`hypotheses.yaml`.

Pointer-only see-findings definitions are not acceptable in Phase 3,
because they break reproducibility and artifact-backed truth.

Exception:
- STRUCTURAL_DIAGNOSTIC entries may be documented as non-tradeable research,
  but must be explicitly labeled and never promoted.
- `frozen_legacy` pointer-only stubs are temporarily allowed only during backfill.
  Phase 3 is not considered fully started until those stubs are replaced by
  canonical frozen definitions in `hypotheses.yaml`.

---------------------------------------------------------------------

# 8) STRUCTURAL_DIAGNOSTIC vs TRADEABLE_HYPOTHESIS

Two classes exist:

STRUCTURAL_DIAGNOSTIC:
- Statistical exploration / mapping
- Not tradeable
- Does not require friction/WF/bootstrap gates
- Must never be promoted

TRADEABLE_HYPOTHESIS:
- Must run full protocol and pass gates:
  - baseline gross / bps8 / bps10
  - WF 60/15/15
  - bootstrap CI + P(mean>0)

Only TRADEABLE hypotheses may be frozen or promoted.

---------------------------------------------------------------------

# 9) BATCH EXECUTION POLICY (QUEUE-DRIVEN)

The queue system is authoritative for execution order:

- `queue.yaml` contains:
  - batch_size (default 10)
  - next_index
  - queue (list of IDs)
  - paused
  - notes

Executor must:
- Refuse to run if `paused: true`
- Run exactly `batch_size` hypotheses starting at `next_index`
- Allow partial final batch only when remaining queue length < batch_size
- Stop immediately on first error
- Advance `next_index` only if all hypotheses in attempted batch succeed
- On success, increment `next_index` by `len(batch_ids)`

---------------------------------------------------------------------

# 10) SAFETY STOPS

Before and during batch execution:

- Check disk free space
- Stop immediately if free space < 1 GB
- For Postgres-backed execution, run DSN preflight in the same shell immediately before batch execution:
  - `export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'`
  - `.venv/bin/python - <<'PY'`
  - `import os, psycopg`
  - `with psycopg.connect(os.environ["RC_DB_DSN"]) as c:`
  - `    with c.cursor() as cur:`
  - `        cur.execute("select 1")`
  - `        print(cur.fetchone())`
  - `PY`
  - Then run `scripts/run_batch_pg.sh` in that same shell without switching context.

On any run failure:
- Write `results/errors/<timestamp>_<hyp>.json`
- Stop batch immediately
- Do not advance `next_index`

---------------------------------------------------------------------

# 11) DATASET FINGERPRINT REQUIREMENT

Each run artifact MUST include:

- symbols (primary + secondary if applicable)
- timeframe
- start_ts (UTC ISO8601)
- end_ts (UTC ISO8601)
- bar_count
- db_path
- db_last_modified (or equivalent)

Guardian must flag any silent drift when comparing like-for-like reruns.

---------------------------------------------------------------------

# 11A) LOGIC HASH INTEGRITY REQUIREMENT

Each TRADEABLE hypothesis definition in `hypotheses.yaml` must include a deterministic
`logic_hash` derived from canonical rule fields.

Artifact requirement:
- each run artifact MUST include the executed `logic_hash`.

Guardian integrity checks:
- compare artifact `logic_hash` vs current `hypotheses.yaml` `logic_hash` for the same ID.
- mismatch MUST be flagged as `logic_drift` integrity failure.
- on `logic_drift`, Guardian must block classification/promotion decisions until:
  - a NEW hypothesis ID is used, or
  - an explicit migration record is logged with artifact references.

No silent hypothesis drift is permitted.

---------------------------------------------------------------------

# 12) MACHINE LEARNING POLICY

ML is permitted for feature ranking and regime discovery only. It may NOT generate
trading signals directly.

Completed ML work:
- HMM regime discovery (`scripts/ml/hmm_regime_discovery.py`) — DONE. Labels in `rc.regime_labels`.
- RF hypothesis generator (`scripts/ml/rf_hypothesis_generator.py`) — DONE. Lessons documented.

Permitted uses:
- Regime clustering (done)
- Feature ranking / importance (XGBoost SHAP — planned next phase)
- Anomaly detection
- Risk adjustment / allocation (after strategy survival)

Forbidden uses:
- Direct PnL optimization
- Automatic parameter tuning
- Generating live trading signals directly from ML output
- Bypassing full hypothesis pipeline

Key lesson: RF rule extraction on validation data hits a 5–6bps ceiling (H125–H139 all FAIL).
Any ML-discovered pattern must become a NEW hypothesis ID and pass the full validation protocol.

---------------------------------------------------------------------

# 13) CONTEXT HYGIENE

After every completed batch:

1) Start a fresh session/chat
2) Re-read `AGENTS.md` and `OPERATING_BRIEF_v3.md`
3) Review `results/summary.json` and tail Findings
4) Continue from artifact-backed state only

No memory-based continuation.

---------------------------------------------------------------------

# 14) FINDINGS TRACEABILITY RULE

Derived findings updates must include artifact references for claims,
including explicit `results/runs/<artifact>.json` identifiers for
classification/freeze/promotion statements.

---------------------------------------------------------------------

# 15) MINIMAL COMPLIANCE CHECKLISTS

Coordinator:
- Role declared
- Queue updated correctly
- Batch assignment <= 10
- No strategy/code edits

Architect:
- Role declared
- New IDs only
- Full canonical YAML definitions
- No result-driven edits

Coder:
- Role declared
- Tooling/code changes only (no hypothesis rule edits)
- No backtest/paper execution
- No manual status/classification claims

Executor:
- Role declared
- Queue honored exactly
- Artifacts/error records written correctly
- No manual PASS/FAIL claims

Guardian:
- Role declared
- Schema/fingerprint checks passed
- Logic-hash integrity checks passed (or drift explicitly flagged/blocked)
- Summary rebuilt deterministically
- Findings derived with artifact references

Capital_Committee:
- Role declared
- Promotion criteria met
- Guardian audit confirmed
- No tuning/test requests

---------------------------------------------------------------------

# 16) DISCIPLINE PRINCIPLE

Markets change.
Artifacts do not lie.

Discipline > novelty.
Validation > intuition.
