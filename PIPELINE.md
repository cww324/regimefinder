# Pipeline Overview
**Updated:** 2026-03-03
**Era:** Phase 3 — Exit logic, regime conditioning, signal expansion (H188–H236 queued)

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

**Supported families in research_family_runner.py (as of 2026-03-03):**
`cross_asset_regime`, `shock_structure`, `volatility_conditioning`, `mean_reversion`,
`range_structure`, `volatility_state`, `efficiency_mean_reversion`, `cross_asset_divergence`,
`funding_regime`, `momentum`, `cross_asset`, `volume_state`, `oi_liq`,
`exit_logic` *(new — H198–H214, apply_exit_logic() scanner)*,
`direction_split` *(new — H215–H220, long/short asymmetry splits)*,
`regime_conditioning` *(new — H229–H234, HMM regime gates on confirmed signals)*

**Key new function:** `apply_exit_logic()` — scans intra-hold bars for early exits
(ATR stop, take profit, trailing stop, breakeven, liq invalidation, slope reversal,
volume collapse). Called inside `build_events()` for all exit_logic IDs.

### ML Pipeline (Phase 2 — complete)
| Script | Purpose |
|--------|---------|
| `scripts/hmm_regime_discovery.py` | Stage 1: HMM regime labeling at 1h → rc.regime_labels ✓ DONE (6,364 rows) |
| `scripts/ml/rf_hypothesis_generator.py` | Stage 2: XGBoost + SHAP walk-forward → hypothesis candidates ✓ DONE (H124–H139) |

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

## Database Status

| Environment | Status | Notes |
|-------------|--------|-------|
| Desktop Postgres | ✓ Active | All data + HMM labels. Paper trader runs here. |
| Laptop | ⚠ No DB | Cloned repo, .venv installed. Needs DB to run hypotheses. |
| Neon/Supabase (planned) | TODO | Migrate desktop DB for laptop access. Free tier sufficient (~150MB). |

**To resume on laptop:** Set `RC_DB_DSN` in `.env`, then:
```bash
source .venv/bin/activate
python -m scripts.run_hypothesis_batch --dsn $RC_DB_DSN
```

## Output Directories

| Directory | Contents |
|-----------|---------|
| `results/runs/` | All hypothesis run JSONs (current era, H39+) |
| `results/archive/` | Older hypothesis run JSONs (H1–H123 era) |
| `results/errors/` | Error artifacts from failed runs |
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
| Phase 2 | H124–H187 | ML-assisted discovery (HMM + RF). Found VS-1/2/3, LQ-1/2/3 signals. 6 new PASS signals deployed to paper trader. |
| Phase 3 | H188–H236 | Exit logic, direction splits, regime conditioning, LQ extensions, VWAP MR. 49 hypotheses queued, none yet run. |

## Current Queue (49 hypotheses — H198–H236 + H188–H197)

Run when DB is accessible: `python -m scripts.run_hypothesis_batch --dsn $RC_DB_DSN`

| Block | H-numbers | Track | Count |
|-------|-----------|-------|-------|
| Exit logic | H198–H214 | ATR/TP/trailing/breakeven/liq/vol exits on confirmed signals | 17 |
| Direction splits | H215–H220 | CA-1/VS-2/VS-3 long-only vs short-only | 6 |
| LQ time-of-day | H221–H224 | LQ-1/LQ-2 Asia (00-08) vs US (12-20) session | 4 |
| Multi-confirm | H225–H228 | OI gate, funding contrarian, slope+liq combo | 4 |
| LQ extensions | H188–H197 | Threshold variants, ETH liq, imbalance, cross-asset | 10 |
| Regime conditioning | H229–H234 | CA-1/VS-2/VS-3 × TRENDING/RANGING/VOLATILE | 6 |
| VWAP MR 365d | H235–H236 | vwap_z extremes on full dataset | 2 |
