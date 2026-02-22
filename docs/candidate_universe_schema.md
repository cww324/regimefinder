# Candidate Universe Schema (Portfolio Construction Input)

Date: 2026-02-21
Owner: Coordinator (planning spec)

## Purpose

Define a deterministic, versioned candidate list artifact used by portfolio-construction hypotheses (`P` IDs).

## File

- Recommended path pattern:
  - `results/candidate_universe/candidate_universe_<timestamp>.json`

## Required Top-Level Fields

- `timestamp_utc` (ISO8601 UTC)
- `candidate_universe_version` (string, immutable identifier)
- `governance_contract_ref` (string: policy/version reference used for selection)
- `source_summary_sha256` (string)
- `source_artifacts` (array of `results/runs/*.json` paths)
- `selection_rules` (object)
- `candidates` (array)

## `selection_rules` Object

- `status_filter` (for example: `["PASS"]`)
- `min_trade_count` (integer)
- `min_fold_count` (integer)
- `cost_mode_primary` (for example: `bps8`)
- `max_pairwise_corr_for_same_bucket` (number)
- `family_diversification_required` (boolean)
- `notes` (string)

## `candidates[]` Entry Schema

- `hypothesis_id` (string, `H###`)
- `family` (string)
- `latest_artifact` (path string)
- `final_status` (string)
- `cost_mode_metrics` (object keyed by `gross`/`bps8`/`bps10`)
- `readiness_flags` (object):
  - `integrity_ok` (bool)
  - `logic_hash_ok` (bool)
  - `sample_ok` (bool)
  - `fold_ok` (bool)
  - `eligible_for_portfolio` (bool)
- `risk_tags` (array of strings)
- `exclude_reason` (string or null)

## Determinism Rules

- Same inputs must produce byte-identical output.
- Candidate ordering must be stable:
  - primary: `eligible_for_portfolio` desc
  - secondary: `family` asc
  - tertiary: `hypothesis_id` numeric asc
- No manual edits after generation; regenerate from inputs instead.
