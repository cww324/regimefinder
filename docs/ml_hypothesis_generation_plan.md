# ML Hypothesis Generation Plan

Last updated: 2026-02-20  
Owner: Coordinator planning reference

## Purpose

Define how to use ML to generate candidate hypotheses for the existing research pipeline, without allowing ML to directly generate live signals or bypass governance.

## In Scope (Now)

- ML-assisted idea generation for new hypothesis candidates.
- Feature ranking and pattern discovery to propose testable rule templates.
- Candidate scoring/ranking for Architect review.

## Out of Scope (Now)

- Direct ML signal generation for trading.
- Automatic parameter tuning for live deployment.
- ML-driven promotion decisions.
- Any bypass of Executor/Guardian workflow.

## Operating Model

1. Data pull
- Use canonical Postgres source (`rc.candles`, `rc.features`).
- Use fixed symbol/timeframe scope for each proposal cycle.

2. ML proposal run (offline only)
- Train simple, interpretable baseline models first:
  - `LogisticRegression` (sanity baseline)
  - `RandomForest` (nonlinear feature interactions)
  - optional `XGBoost/LightGBM` after baseline stability
- Use strict time-based splits (no random shuffle).

3. Candidate proposal artifacts
- ML run outputs candidate proposal files under `results/ml_candidates/`.
- Each proposal must include:
  - candidate label/id (temporary)
  - target family
  - WHY
  - RULES (human-readable)
  - PARAMETERS (fixed, explicit)
  - FAILURE_CONDITIONS
  - EXPECTED_FAILURE_MODE
  - model metadata (`model_type`, `model_hash`, `seed`)
  - data metadata (`start_ts`, `end_ts`, `symbols`, `feature_list_hash`)

4. Architect conversion
- Architect selects a limited subset and writes NEW `Hxxx` IDs in `hypotheses.yaml`.
- No direct execution from ML proposal artifacts.

5. Normal validation path
- Executor runs new IDs through standard pipeline.
- Guardian audits artifacts and summary.
- Capital_Committee decisions remain artifact-backed.

## Anti-Overfit Controls

- Time split discipline with embargo/purge around boundaries.
- Proposal cap per cycle (small fixed number).
- No same-ID retuning loops.
- Any rule change requires new ID.
- Keep a non-ML baseline track for comparison.

## Diversity Controls for Large Proposal Batches

If running large candidate batches (for example 100-200 proposals), enforce diversity constraints so output is not just minor variants of one idea.

1. Family quotas
- Set maximum proposals per family per cycle (example: <=20 per family).
- Require minimum family coverage (example: at least 8-10 distinct families represented).

2. Template buckets
- Define required buckets (example: mean-reversion, breakout/range, cross-asset, volatility-state, volume-structure, session/time-of-day, portfolio-construction).
- Enforce minimum count per bucket.

3. Similarity filtering
- Reject candidates above a similarity threshold to already-selected proposals:
  - rule-text similarity
  - feature-set overlap
  - parameter-vector distance

4. Parameter de-duplication
- Within a family, block near-duplicate parameterizations (small threshold/window perturbations only).

5. Novelty-aware ranking
- Rank by composite score:
  - edge proxy
  - robustness proxy
  - novelty bonus / overlap penalty

6. Architect acceptance caps
- Architect acceptance is capped per family/bucket (not just top-N overall).
- Example: accept at most 1-2 from each family in a cycle.

## Minimal Technical Additions

Planned scripts:
- `scripts/ml_generate_candidates.py`
- `scripts/ml_score_candidates.py`

Planned artifact path:
- `results/ml_candidates/`

Optional later DB tracking:
- `rc.ml_runs`
- `rc.ml_candidate_proposals`

## Suggested Phase Rollout

Phase 0: Dry-run research only
- Generate candidate proposals but do not convert to hypotheses.
- Validate proposal quality and stability.

Phase 1: Controlled adoption
- Architect converts a small subset to new IDs.
- Run full governance pipeline unchanged.

Phase 2: Scaled candidate generation
- Increase proposal breadth only if Phase 1 produces stable, non-overfit outcomes.
- Enable diversity controls before permitting large proposal counts.

## Readiness Checklist (Before First ML Cycle)

- Canonical feature set documented and versioned.
- Time-split and embargo rules written down.
- Proposal schema finalized.
- Proposal cap chosen.
- Architect review criteria defined.

## Success Criteria

- ML proposals produce a measurable increase in high-quality, distinct hypothesis ideas.
- No increase in governance drift or untraceable decisions.
- New hypotheses remain reproducible and artifact-auditable end-to-end.
