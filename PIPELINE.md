# Pipeline Overview
**Updated:** 2026-02-23
**Era:** Phase 2 — ML-assisted hypothesis discovery (HMM + RF)

This document is the orientation guide. Read it to understand which scripts are active,
which are reference material, and where new work lives.

---

## Active Pipeline (touch these regularly)

### Data Infrastructure
| Script | Purpose |
|--------|---------|
| `scripts/backfill_5m.py` | Fetch OHLCV candles from Coinbase → Postgres |
| `scripts/backfill_derivatives.py` | Fetch funding rates / OI from Hyperliquid → Postgres |
| `scripts/compute_features.py` | Compute all features from candles → rc.features |
| `scripts/ingest_5m.py` | Live bar ingest (used by paper runner) |

### Research Pipeline
| Script | Purpose |
|--------|---------|
| `scripts/research_family_runner.py` | Core backtest engine — all hypothesis families route through here |
| `scripts/run_hypothesis_batch.py` | Batch runner — runs multiple H-numbers in sequence |
| `scripts/run_batch_pg.sh` | Shell wrapper for unattended batch execution |

### ML Pipeline (Phase 2 — new)
| Script | Purpose |
|--------|---------|
| `scripts/ml/hmm_regime_discovery.py` | Stage 1: HMM regime labeling at 1h → rc.regime_labels *(not yet built)* |
| `scripts/ml/rf_hypothesis_generator.py` | Stage 2: XGBoost + SHAP walk-forward → hypothesis candidates *(not yet built)* |

### Live Paper Trading
| Script | Purpose |
|--------|---------|
| `scripts/run_paper_h32_live.py` | H32 live paper execution (UNDER REVIEW) |
| `scripts/capture_paper_signal_snapshots.py` | Snapshot paper signals to rc.paper_signal_snapshots |

### Reporting / Health
| Script | Purpose |
|--------|---------|
| `scripts/health.py` | DB health check |
| `scripts/audit_runs.py` | Audit hypothesis run artifacts |
| `scripts/build_summary.py` | Build summary JSON from results |
| `scripts/sanity_compare_legacy_vs_rc.py` | Compare legacy SQLite vs Postgres output |

---

## Reference Scripts (useful patterns — don't delete)

These are not part of the active run loop but contain patterns worth referencing
when building new ML components.

| Script | Why keep it |
|--------|-------------|
| `scripts/drift_study.py` | Regime bucketing + forward-return aggregation pattern |
| `scripts/rv_drift_study.py` | Rolling percentile rank + regime bucketing — core RF feature pattern |
| `scripts/hypothesis_studies.py` | Multi-dimensional bucketing with stat filtering — RF candidate validation |
| `scripts/run_paper_portfolio.py` | Risk control framework, exposure caps, portfolio metrics aggregation |
| `scripts/h2s_vol_uncertainty.py` | Walk-forward fold iteration + bootstrap CI pattern |
| `scripts/ablation.py` | Parameter sweep harness — adapt for RF hyperparameter sensitivity |
| `scripts/run_paper_forward.py` | Stateful forward-mode execution pattern (future live ML inference) |
| `scripts/mr_drift_study.py` | VWAP z-score bucketing pattern |
| `scripts/time_effects_study.py` | Calendar bucketing (hour-of-day / day-of-week effects) |
| `scripts/vol_expansion_study.py` | Multi-condition compound regime logic |
| `scripts/daily_drift_study.py` | Daily resampling + bucketing template |

---

## Archived / Superseded

| Script | Reason |
|--------|--------|
| `scripts/research_h32_runner.py` | Superseded by `research_family_runner.py` |
| `scripts/research_h33_runner.py` | Superseded by `research_family_runner.py` |
| `logs/archive/` | Old h2s sweep CSVs and early study outputs |

---

## Output Directories

| Directory | Contents |
|-----------|---------|
| `results/archive/` | All hypothesis run JSONs (H1–H123 era) |
| `results/ml/hmm/` | HMM regime discovery outputs |
| `results/ml/rf/` | RF hypothesis generator outputs |
| `logs/` | Active logs (backfill, live paper trading) |

---

## Key Documents

| File | Purpose |
|------|---------|
| `AI_AGENT.md` | Operating brief — read first in every session |
| `REGIME_FRAMEWORK.md` | H124+ hypothesis design rules, three-layer architecture |
| `FINDINGS_365D.md` | 365d era results, organized by signal family |
| `SIGNAL_REGISTRY.md` | Confirmed signal shortcodes (CA-1 through CA-5) |
| `VALIDATION_IMPROVEMENTS.md` | Pending protocol upgrades (FDR, permutation, Sharpe gate) |
| `docs/hmm_regime_plan.md` | HMM regime discovery design spec (build first) |
| `docs/rf_experiment_plan.md` | RF signal discovery design spec (build second) |

---

## Phase History

| Phase | Era | Description |
|-------|-----|-------------|
| Phase 1 | H1–H123 | Manual hypothesis design. 25 PASS signals found, all CA-family. Tagged: `phase1-end` |
| Phase 2 | H124+ | ML-assisted discovery via HMM + RF. Regime-aware three-layer architecture. |
