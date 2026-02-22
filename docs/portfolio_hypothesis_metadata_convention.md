# Portfolio Hypothesis Metadata Convention

Last updated: 2026-02-20
Owner: Coordinator planning convention

## Purpose

Keep portfolio-construction hypotheses (`P` IDs) easy to group and audit across multiple portfolio research tracks without renaming historical IDs.

## Required Metadata for New `P` IDs

Add these keys under `parameters.fixed` for every new portfolio-construction hypothesis:

- `portfolio_track_id`
  - Short stable label for the portfolio research track.
  - Example: `core6_v1`, `expanded_mix_v2`

- `candidate_universe_version`
  - Version label for the strategy universe snapshot used by this hypothesis.
  - Example: `u_core6_2026q1`

- `construction_variant`
  - Construction method label.
  - Example: `equal_weight_dedup`, `rank_weight_30d`, `regime_router_v1`

## Optional Metadata

- `router_regime_version` (for router-style `P` hypotheses)
- `weighting_kernel_version`
- `risk_cap_profile_id`

## Example Snippet

```yaml
parameters:
  lookback_days: 180
  horizon_bars: 8
  fixed:
    portfolio_track_id: core6_v1
    candidate_universe_version: u_core6_2026q1
    construction_variant: rank_weight_30d
```

## Notes

- Do not retroactively rewrite older `P` IDs unless explicitly scheduled.
- Keep existing sequential `P` IDs for traceability; use metadata to express track/group membership.

