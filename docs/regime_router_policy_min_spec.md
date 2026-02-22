# Regime Router Minimal Policy Spec

Date: 2026-02-21
Owner: Coordinator (planning spec)

## Objective

Define a fixed-rule portfolio router that maps detected regime state to allowed strategies and weights, including a default no-trade state.

## Inputs

- `candidate_universe_version`
- Current regime features (predefined, fixed)
- Regime classifier output:
  - `regime_label`
  - `confidence`
- Strategy health state:
  - data freshness
  - guardrail status
  - execution availability

## Core Policy

1. Regime classification is fixed-rule and versioned.
2. If `confidence < threshold`, route to `NO_TRADE` or reduced-risk profile.
3. For each regime, use predeclared allowlist of hypothesis IDs only.
4. Apply fixed weights per regime (or fixed weighting function).
5. Enforce hard caps:
- max single-strategy weight
- max single-family weight
- max gross exposure
6. If any required data/health check fails, route to `NO_TRADE`.

## Required Config Fields

- `portfolio_track_id`
- `candidate_universe_version`
- `construction_variant`
- `regime_definitions_version`
- `confidence_threshold`
- `regime_to_allowlist` (map)
- `regime_to_weights` (map)
- `risk_caps` (object)
- `transition_rules` (cooldown/hysteresis/min-hold)

## Validation Gates Before Live Paper

- Heat gates pass (correlation/family concentration/strategy concentration)
- Post-cost robustness pass (gross, bps8, bps10 where required)
- Time-slice stability pass
- Execution-lag/slippage stress pass
- Deterministic artifact reproducibility pass

## No-Trade Policy

- `NO_TRADE` is a first-class regime output, not an exception.
- Trigger when:
  - low confidence
  - contradictory regime signals
  - health/preflight failures
  - none of the allowed strategies pass current health checks
