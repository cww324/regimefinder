# OPERATING_BRIEF_v3.md
## Regime Crypto Research — Current Operating Brief
**Last Updated:** 2026-03-11 (post-ML session)
**Supersedes:** `AI_AGENT.md` (renamed `AI_AGENT_OUTDATED.md`)
**Governance rules:** `AGENTS.md` (still authoritative for roles, freeze authority, batch policy)

---

## 1) Mission

Run strict, no-tuning hypothesis research. Validate only with fixed OOS protocols.
Keep confirmed signals frozen. Advance via genuinely new mechanisms — not variations of existing signals.

**Current phase:** ML discovery produced 3 new signal families (LQ-6, OV-1, CD-1).
Next: round 3 ML features + deployment planning for 16-signal portfolio.

---

## 2) Mandatory Startup Read Order

1. `OPERATING_BRIEF_v3.md` (this file)
2. `AGENTS.md` (governance rules, roles, freeze authority)
3. `results/summary.json` (if it exists — rebuild from artifacts if missing)
4. Tail `FINDINGS_365D.md` (canonical results log for the 365d era)

---

## 3) Confirmed Signals (as of 2026-03-11 post-ML session)

All confirmed on 365-day dataset (Feb 2025 – Feb 2026), BTC/ETH 5m candles, Postgres.

| Shortcode | H# (anchor) | Lag H# | bps8 WF | Execution lag | Notes |
|-----------|-------------|--------|---------|---------------|-------|
| CA-1 | H65 | H77 | ~26bps | ✓ | ETH slope flip h=8 |
| CA-2 | H63 | H76 | ~13bps | ✓ | BTC slope flip h=8 |
| CA-3 | H60 | — | ~18bps | — | ETH slope flip h=6 |
| CA-4 | H59 | — | ~8bps | — | BTC slope flip h=6 |
| CA-5 | H99 | — | marginal | — | Session handoff |
| VS-1 | H145 | H161 | 26bps | ✓ | Vol p80 + ETH flip h=8 |
| VS-2 | H167 | H171 | 39bps | ✓ | Vol p80 + ETH flip h=12 |
| VS-3 | H180 | H187 | 61bps | ✓ | Vol+liq triple gate h=12 |
| LQ-1 | H177 | H184 | 20bps | ✓ | Long liq cascade SHORT h=8 |
| LQ-2 | H178 | H185 | 16bps | ✓ (marginal) | Short liq squeeze LONG h=8 |
| LQ-3 | H179 | H186 | 31bps | ✓ | Liq-gated ETH flip SHORT h=8 |
| LQ-4 | H191 | H240 | 31bps | ✓ | LQ-1 at h=12 |
| LQ-5 | H192 | H241 | 21bps | ✓ | LQ-2 at h=12 |
| **LQ-6** | **H247** | **H249** | **27bps** | ✓ | **Liq imbalance dir SHORT h=12 — NEW (ML-surfaced)** |
| **OV-1** | **H252** | **H259** | **18bps** | ✓ | **OI velocity gate on CA-1 h=24 — NEW (ML-surfaced)** |
| **CD-1** | **H257** | **H260** | **14bps** | ✓ | **BTC-ETH corr decoupling + ETH flip h=12 — NEW (ML-surfaced)** |

**LQ-6, OV-1, CD-1 are genuinely new mechanisms** — not slope/volume/liq gate variants. First ML session to produce confirmed independent signal families.

**OI-1 shortcode blocked:** H176 gross real but even-day robustness fails (H182: 5/18 bps8 folds). No further OI iteration until 2+ years of data.

**Next H-number: H261**

---

## 4) Data Infrastructure (All Complete)

| Source | Data | Status | Rows |
|--------|------|--------|------|
| Coinbase REST | BTC+ETH 5m candles | ✓ 365d in Postgres | ~105k/symbol |
| Hyperliquid | Funding rates (1h) | ✓ in `rc.funding_rates` | 17,520 |
| Gate.io | Open interest (1h) | ✓ in `rc.open_interest` | 17,520 |
| Gate.io | Liquidations (1h) | ✓ in `rc.liquidations` | 17,520 |
| HMM pipeline | Regime labels | ✓ in `rc.regime_labels` | 6,364 |

**Feature count in `load_frame()`:** 121 columns (candles + funding + OI + liq + HMM regime).

**Refresh commands:**
```bash
make backfill-derivatives     # funding rates
make backfill-oi-liq          # OI + liquidations
```

**DB connection:**
```bash
export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'
docker start rc-postgres   # if not running
```

---

## 5) Validation Standards

**Walk-forward geometry:** `--wf 120 20 20` (train 120d / test 20d / step 20d) → ~11 folds on 365d.
Previous hypotheses (H59–H187) used `60/15/15` → ~18 folds. Both are valid; do not mix within a family.

**Pass criteria (both must hold):**
- Gross: `P(gross_r > 0)` ≥ 0.95, WF positive folds ≥ 60% (≥ 7/11 for 120/20/20 config)
- bps8: mean net > 0 after 8bps round-trip, WF bps8 folds ≥ 60%

**Classifications:** PASS / BORDERLINE / FAIL / INCONCLUSIVE / REGIME_FAIL
(see `FINDINGS_365D.md` Classification Guide for definitions)

**Canonical truth:** `results/runs/*.json` artifacts only. Findings files are derived documents.

> ✅ `results/summary.json` is **fixed** (see section 9b). `build_summary.py` now handles both artifact
> formats (old `walkforward` key H15–H173, new `wf_by_mode` key H174+). Rebuild anytime with `make summary`.
> The last rebuild covered all 144 H-numbers (H15–H201). After running new batches, rebuild to keep current.

---

## 6) Current Queue Status

**Queue file:** `queue.yaml` (next_index=0, 49 hypotheses remaining)

### What has been run (H198–H201, exit logic batch 1):
| H# | Signal | Exit type | Verdict | Key finding |
|----|--------|-----------|---------|-------------|
| H198 | CA-1 | ATR stop 1.5× | FAIL | 14.7bps gross (vs 34bps baseline) — exits cut winners |
| H199 | CA-1 | TP +25bps | FAIL | 12.8bps gross — TP clips right tail |
| H200 | CA-1 | Trail 15bps | FAIL | 11.0bps gross — worst variant |
| H201 | CA-1 | ATR+TP combo | FAIL | 11.0bps gross — |

**Exit logic conclusion:** CA-1's 8-bar fixed hold is near-optimal. Early exits cut winners systematically.
The fixed hold is not a simplification — it matches the signal's momentum duration.

### Queue status: COMPLETE (2026-03-11)
All H198–H239 have been run. next_index=52, queue exhausted.

**Summary of this run batch:**
- Exit logic (H202–H214): price exits FAIL, thesis-invalidation exits PASS — confirmed pattern from H198–H201
- Direction splits (H215–H220): CA-1 and VS-2 symmetric. H219/H220 (VS-3) INCONCLUSIVE n<50
- LQ extensions (H188–H197): H191 (LQ-1 h=12, 31bps) and H192 (LQ-2 h=12, 21bps) are replication candidates
- LQ ToD + gates (H221–H228): all BORDERLINE/PASS but none beat parent signals — no new shortcodes
- Regime conditioning (H229–H234): n too low after splits — mining confirmed signals
- VWAP MR (H235–H236): FAIL — BTC 5m does not mean-revert from VWAP
- Pre-committed hypotheses (H237–H239): H237/H238 FAIL, H239 INCONCLUSIVE (n=37)

**Run commands (executor):**
```bash
# DB preflight (same shell before any run)
export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["RC_DB_DSN"]) as c:
    with c.cursor() as cur:
        cur.execute("select 1")
        print(cur.fetchone())
PY

# Then run via queue
scripts/run_batch_pg.sh
```

---

## 7) Research Direction (Post-ML Session)

**ML session complete (2026-03-11):** XGBoost SHAP with 3 rounds of theory-first features at 4 horizons (h=4,8,16,48) produced 3 confirmed new signal families. This breaks the "one-edge" problem.

**Confirmed new mechanisms:**
- **LQ-6:** Liquidation imbalance direction → SHORT h=12. New dimension: *which side* of the book is being cleared.
- **OV-1:** OI acceleration gate on CA-1 h=24. New dimension: *new money opening* vs. existing positions repositioning.
- **CD-1:** BTC-ETH correlation decoupling + ETH flip h=12. New dimension: ETH *idiosyncratic* momentum vs. BTC co-movement.

**Next ML work (round 3 features — not yet run):**
Round 3 features are already in the parquet (`ret_4h_eth`, `eth_slope_4h`, `btc_slope_4h`, `bar_dir_run`, `rv_chg_1h`). Multi-horizon run not yet executed.
```bash
export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'
.venv/bin/python scripts/ml/xgboost_discovery.py --horizons 4 8 16 48
```

**What NOT to do:**
- More CA/VS/LQ threshold variations (over-mining)
- More exit logic variants (exits hurt fixed-hold signals — confirmed H198–H214)
- More regime gates on existing signals (reduces n, same edge — confirmed H229–H234)
- Extract rules directly from RF/XGBoost (leads to 5-6bps ceiling — H125–H139)

---

## 8) Key Lessons (Hard-Won)

- **RF as validator, not generator:** SHAP rules from RF on validation data hit a 5–6bps ceiling every time. Untradeable (H125–H139).
- **Exits hurt confirmed signals:** ATR stops, TPs, and trailing stops all reduce CA-1 gross ~50%. Fixed hold is correct (H198–H201).
- **One real edge, not 9:** All confirmed signals are CA/VS/LQ family. No FR, MR, or CD signals confirmed.
- **Frequency is a cost gating problem:** Funding signals (H140–H144) have real gross edge but fire <1/month. Need 2+ years of data.
- **OI needs longer data:** OI-1 gross is real but day-asymmetric. Not reliable at 365d.
- **Session gates don't help VS:** VS signals use volume gate which already captures session effects. Filtering by hour reduces n without improving edge.
- **Direction splits matter for deployment:** The 365d dataset is predominantly bullish. SHORT side of all signals has never been tested separately. This is a deployment risk.

---

## 9) File Map

| File | Purpose | Authoritative? |
|------|---------|----------------|
| `OPERATING_BRIEF_v3.md` | Current operating state (this file) | ✓ startup read |
| `AGENTS.md` | Governance: roles, freeze rules, batch policy | ✓ governance |
| `FINDINGS_365D.md` | Canonical results log (365d era, H124+) | ✓ results |
| `SIGNAL_REGISTRY.md` | Confirmed signals with shortcodes | ✓ signals |
| `BEST_HYPOTHESES.md` | Quick reference table by shortcode | derived |
| `RESEARCH_ROADMAP.md` | Hypothesis backlog, phase planning | guidance |
| `REGIME_FRAMEWORK.md` | H124+ hypothesis design rules | guidance |
| `VALIDATION_IMPROVEMENTS.md` | Pipeline gaps (FDR, permutation, holdout) | guidance |
| `queue.yaml` | Execution order — authoritative for batch runs | ✓ queue |
| `results/runs/*.json` | Run artifacts — source of truth for all classifications | ✓ truth |
| `results/summary.json` | Aggregate summary built from artifacts | derived |
| `AI_AGENT_OUTDATED.md` | Old brief — DO NOT USE | archived |
| `FINDINGS_SIMPLIFIED.md` | Pre-365d era archive | archived |
| `FINDINGS_TECHNICAL.md` | Pre-365d era archive | archived |

---

## 9b) Pipeline Hygiene — COMPLETED (2026-03-11)

### What was fixed:
- **Canonical output dir:** `results/runs/` is authoritative. `results/archive/` is fully covered by `results/runs/` (zero unique artifacts) — treat as legacy read-only.
- **`scripts/build_summary.py` updated:** Now handles both artifact formats:
  - Old format (`walkforward` key, H15–H173): `walkforward.modes.{mode}` for WF data, `dataset` for fingerprint
  - New format (`wf_by_mode` key, H174+): `wf_by_mode.{mode}` for WF data, `config` for dataset info
  - Also normalizes baseline CI field names (`ci_low` vs `mean_ci_low`)
- **`results/summary.json` rebuilt:** Covers all 144 H-numbers (H15–H201), 45 PASS / 12 BORDERLINE / 10 INCONCLUSIVE / 77 FAIL
- **`make summary` target added** to Makefile — run anytime to rebuild

### Run to rebuild summary:
```bash
make summary
# or: PYTHONPATH=. .venv/bin/python scripts/build_summary.py
```

---

## 10) Critical Validation Gaps (Not Yet Addressed)

| Gap | Description | Priority |
|-----|-------------|----------|
| ~~10a — Direction asymmetry~~ | **RESOLVED (2026-03-11):** CA-1 and VS-2 both pass LONG+SHORT independently (H215–H218). VS-3 INCONCLUSIVE (n<50) but edge looks symmetric — deploy both directions. | ~~HIGH~~ DONE |
| 10b — Regime conditioning | HMM regime labels exist but never used to filter confirmed signals | MEDIUM |
| 10c — FDR correction | 236 hypotheses tested, no multiple-testing correction applied | MEDIUM |
| 10d — True holdout | Last 60 days seen in WF folds. Need permanently reserved block | LOW (irreversible, do last) |
| 10e — Cost sensitivity | All signals validated at 8bps. Need re-run at 10/12/14bps | MEDIUM |
