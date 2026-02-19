# Paper Portfolio Protocol

Purpose: standardize paper testing for multiple `paper_candidate` hypotheses using one execution model and auditable outputs.

## 1) Scope and Roles

- Executor runs paper tests (standalone and combined).
- Guardian validates outputs and updates derived artifacts.
- Capital_Committee reviews promotion decisions from audited evidence only.

## 2) Candidate Set

- Default current set: `H76,H77,H79,H81,H78,H82` (update as governance decisions change).
- All candidates must be frozen rule definitions (no tuning during paper protocol).

## 3) Execution Model

- Use one shared execution model across all candidates:
  - identical fill assumptions
  - identical cost assumptions
  - identical bar timing/entry-exit semantics
- Do not run independent conflicting bots for portfolio evaluation.
- Use many signal modules + one net execution layer.

## 4) Test Phases

### Phase A: Standalone Paper

- Run each candidate independently on:
  1. `180d` screening window
  2. `365d` confirmation window (for survivors)

### Phase B: Combined Portfolio Paper

- Run all selected survivors together using one net position/execution policy.
- Same windows:
  1. `180d` combined
  2. `365d` combined confirmation

## 5) Portfolio Aggregation Rules

- Each strategy emits a signed target score (or target position signal).
- Convert to normalized strategy weights.
- Aggregate to net per-asset target exposure.
- Enforce risk caps before order generation.

Required controls:
- max gross exposure
- max per-asset exposure
- max strategy contribution
- cooldown / minimum spacing control
- turnover cap
- daily loss stop / circuit-breaker

## 6) Required Metrics (Per Run)

- Net return (after costs)
- Max drawdown
- Trade count and turnover
- Win rate and expectancy
- Monthly (or weekly) stability profile
- Cost sensitivity view (where available)
- Cross-strategy correlation and concentration stats (combined phase)

## 7) Artifact Requirements

- Persist run outputs under deterministic, timestamped artifact paths.
- Include dataset fingerprint fields in each artifact:
  - `start_ts`
  - `end_ts`
  - `bar_count`
  - `db_path`
  - `db_last_modified`
- Include protocol metadata:
  - window length (`180d` or `365d`)
  - cost model
  - execution mode (standalone vs combined)

## 8) Decision Gates

- Standalone gate:
  - candidate must remain stable after costs and pass minimum coverage requirements.
- Combined gate:
  - portfolio must improve risk-adjusted profile without unstable concentration.
- Portfolio heat gate (combined phase, Guardian-audited):
  - max pairwise cross-strategy correlation in active set: `<= 0.75`
  - max single-strategy PnL share: `<= 0.40`
  - max single-family active weight share: `<= 0.60`
  - any breach blocks promotion and routes to Architect as a new portfolio-construction hypothesis.
- If standalone candidates remain profitable but combined performance is weak/unstable:
  - treat this as a portfolio-construction hypothesis failure, not evidence that standalone rules are invalid.
  - route follow-up to Architect as a NEW hypothesis ID for combination/weighting logic (no edits to existing frozen IDs).
- Any promotion recommendation requires Guardian PASS audit for involved artifacts.

## 9) Diversification Requirement

- A strong single family is necessary but not sufficient for promotion.
- Portfolio track must include discovery of at least one additional distinct signal family
  with independent edge characteristics before live-candidate consideration.
- Similar-family variants are allowed for robustness, but they do not count as diversification.

## 10) Operational Discipline

- Run DB preflight in the same shell immediately before DB-dependent runs.
- Use Postgres-safe executor entrypoint.
- On failure:
  - write `results/errors/<timestamp>_<id>.json`
  - stop run
  - do not advance queue/index states unless policy conditions are met.

## 11) Reporting Sequence

1. Executor posts run artifacts and command provenance.
2. Guardian audits and rebuilds summary/findings.
3. Capital_Committee issues status decisions with explicit artifact references.
