# Coordinator Next TODOs

Last updated: 2026-02-21
Role owner: Coordinator

## Immediate Sequence

0. Active first priority (highest):
- PASS-inventory readiness map completed: `docs/pass_inventory_readiness_map_2026-02-21.md`.
- Run PASS rerun Batch 1 (10 IDs) from `queue.yaml`, then Guardian audit.
- After Batch 1 closeout, queue Batch 2 and Batch 3 from readiness map.

1. Executor
- Finish active run:
  - `results/paper/20260220T065602Z_P01_P04_combined_180d.json` (in progress)
- Report:
  - artifact path
  - exit code
  - any new `results/errors/*_paper_portfolio.json`

2. Guardian
- Audit latest `P01-P04` combined 180d artifact.
- Publish audit JSON under `results/audit/`.
- Update derived findings with artifact references.

3. Executor (after Guardian scope closes)
- Perform 365d data expansion/backfill and feature recompute (same-shell DSN discipline).
- Run `P01-P04` combined 365d artifact.

4. Guardian
- Audit combined 365d artifact.
- Update findings and summary-derived status references.

## Coder Backlog

1. Add progress reporting to `scripts/run_paper_portfolio.py`:
- phase milestones
- bounded periodic progress counters
- elapsed + rough ETA
- preserve artifact schema/output values

2. Add runner support for `H114-H120` in `scripts/research_family_runner.py`:
- route branches
- required feature plumbing
- fail-fast preflight/validation

3. Portfolio runner performance optimization (high priority):
- Target file: `scripts/run_paper_portfolio.py`
- Optimize repeated recomputation paths (frame/member-run reuse and/or bounded parallelism).
- Hard constraint: no change to research math, classification inputs, or artifact schema.
- Required validation:
  - same input config -> equivalent output metrics/artifact fields
  - deterministic ordering preserved
  - runtime improvement documented

## Architect Backlog

- Continue new `H`-series idea generation in 5-10 ID batches after `H120`, with orthogonal families and canonical blocks.

## Forward Planning

- After `P01-P04` closeout, open `P05+` regime-router portfolio-construction track.
- Keep new `P` IDs aligned with metadata convention:
  - `portfolio_track_id`
  - `candidate_universe_version`
  - `construction_variant`
