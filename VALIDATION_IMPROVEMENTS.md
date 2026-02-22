# Validation Improvements
**Created:** 2026-02-22
**Status:** Active — describes gaps in current validation framework and how to address them.

---

## 1. Current Validation Stack (What We Have)

For each hypothesis, the pipeline currently runs:
1. **Baseline stats**: n, win rate, mean, std, bootstrap 95% CI, P(mean>0) — on full lookback window
2. **Walk-forward (60/15/15)**: 7 folds of 15-day test windows, positive fold %, aggregate mean + CI
3. **Cost modes**: gross, 8bps, 10bps round-trip

Classification: `PASS / BORDERLINE / FAIL / INCONCLUSIVE` based on:
- `n >= 50` and `fold_count >= 5` (else INCONCLUSIVE)
- Baseline CI lower bound > 0 AND mean > 0 → PASS baseline
- WF mean > 0 AND positive_fold_pct >= 60% AND WF CI lower > 0 → PASS WF
- Final = combination of baseline and WF statuses

This is a reasonable foundation. The gaps below are improvements, not replacements.

---

## 2. Gap 1: Multiple Testing Correction (Critical)

### The Problem
With 100+ hypotheses tested, running each at 5% significance means you expect ~5 false positives by chance alone. The current framework treats each hypothesis independently, so a PASS on hypothesis H95 might be a false discovery with no real edge.

### Fix: Benjamini-Hochberg False Discovery Rate (BH-FDR)
BH-FDR controls the *expected proportion* of false positives among all PASSed hypotheses. It is less conservative than Bonferroni (which requires adjusting α to 0.05/100 = 0.0005) while still providing meaningful protection.

**How to implement:**
```python
# After running a full batch, collect P(mean>0) values for all hypotheses
# in the batch. Treat (1 - P(mean>0)) as the p-value for each.

from scipy.stats import false_discovery_control

p_values = [1.0 - result["p_mean_gt_0"] for result in batch_results]
# BH correction — returns adjusted p-values
adjusted = false_discovery_control(p_values, method='bh')

# A hypothesis survives correction if adjusted p-value < 0.05
for i, hyp in enumerate(batch_results):
    hyp["bh_adjusted_p"] = adjusted[i]
    hyp["survives_fdr_05"] = adjusted[i] < 0.05
```

**When to apply:** At the end of each batch run, report how many hypotheses survive BH-FDR at α=0.05. Add `survives_fdr` as a field in the artifact JSON. A hypothesis that PASSes individual gates but fails BH-FDR correction should be marked BORDERLINE, not PASS.

**Note:** BH-FDR applies across a batch, not within a single hypothesis. The unit of correction is the set of hypotheses tested in one research campaign (e.g., H86–H100 was one batch).

---

## 3. Gap 2: Permutation / Label-Shuffle Test

### The Problem
Bootstrap CI tells you how stable your estimate of the mean is, but not whether the *timing* of your signals carries information. A signal that fires randomly would have the same bootstrap CI shape if it happened to catch good bars by luck.

### Fix: Permutation Test
Shuffle the timestamps of forward returns (keeping signal structure intact) and re-run the bootstrap. The signal has real timing information only if its P(mean>0) is significantly higher than the permuted distribution.

**How to implement:**
```python
def permutation_test(
    gross_r: np.ndarray,
    signal_dir: np.ndarray,
    n_permutations: int = 1000,
    seed: int = 42,
) -> dict:
    """
    Shuffle fwd_r timestamps and recompute mean. If real mean > 95th pct of
    permuted means, signal timing carries information.
    """
    rng = np.random.default_rng(seed)
    real_mean = float((gross_r).mean())
    perm_means = []
    for _ in range(n_permutations):
        shuffled = rng.permutation(gross_r)
        perm_means.append(float(shuffled.mean()))
    perm_means = np.array(perm_means)
    p_perm = float((perm_means >= real_mean).mean())  # fraction of permutations >= real
    return {
        "real_mean": real_mean,
        "perm_mean_p95": float(np.quantile(perm_means, 0.95)),
        "p_permutation": p_perm,  # lower is better; want < 0.05
        "passes_permutation_test": p_perm < 0.05,
    }
```

Add this to `compute_for_cost()` in `research_family_runner.py` and report in the artifact JSON. A hypothesis that PASSes WF+bootstrap but fails the permutation test is suspect.

---

## 4. Gap 3: Risk-Adjusted Metrics (Sharpe Ratio Gate)

### The Problem
The current gate is: `mean > 0 AND CI_low > 0`. Two hypotheses:
- H_A: mean=+0.001, std=0.002, n=200
- H_B: mean=+0.001, std=0.020, n=200

Both PASS the current gate identically. H_B is 10x riskier per unit of return. In live trading, H_B would require much tighter position sizing to achieve the same risk budget.

### Fix: Per-Fold Sharpe Ratio in WF
Add Sharpe ratio to each WF fold and to the aggregate:

```python
def fold_sharpe(returns: np.ndarray, bars_per_year: int = 105120) -> float:
    """
    Annualized Sharpe ratio. bars_per_year = 365 * 24 * 12 for 5m bars.
    Use per-trade returns, not bar-level returns.
    """
    n = len(returns)
    if n < 2:
        return 0.0
    mean = float(returns.mean())
    std = float(returns.std(ddof=1))
    if std == 0:
        return 0.0
    # Scale by sqrt(trades per year) — approximate annualization
    # For 5m data, assume ~2-5 trades per day = ~730-1825 trades/year
    trades_per_year = float(n) / (180.0 / 365.0)  # adjust for actual data span
    return float((mean / std) * np.sqrt(trades_per_year))
```

**Gate addition:** A hypothesis with aggregate WF Sharpe < 0.5 after friction should be classified as BORDERLINE even if mean > 0. Target for deployment: WF Sharpe > 1.0 after friction.

---

## 5. Gap 4: MAE Gate (Currently Computed, Never Used)

### The Problem
`mae_proxy_median` is calculated and stored in diagnostics but never referenced in `classify_mode()`. The MAE (Maximum Adverse Excursion) tells you the worst the trade goes against you during the holding period. A signal with median MAE of -1.5% on 30-minute holds is extremely difficult to trade live — you'd be stopped out constantly.

### Fix: Use MAE as a Quality Filter
Add to `classify_mode()` or as a diagnostic flag:

```python
# In classify_mode() or as a post-classification filter:
mae_med = diagnostics.get("mae_proxy_median")
if mae_med is not None and mae_med < -0.005:  # worse than -0.5%
    # Signal consistently goes deeply against entry before reverting
    # Flag as hard to execute live
    flags.append("HIGH_MAE_RISK")
```

**Guideline thresholds:**
- MAE median > -0.002 (better than -0.2%): Clean signal, easy to hold
- MAE median -0.002 to -0.005: Acceptable, monitor in paper trading
- MAE median < -0.005: Difficult to execute live, stops will trigger

---

## 6. Gap 5: Trade Independence (Overlapping Returns)

### The Problem
`dedup_idx` enforces a minimum gap of `horizon` bars between signals. With `horizon=6`, two trades can be taken 6 bars apart (30 minutes). But each trade holds for 6 bars, meaning their holding periods **overlap by up to 5 bars**. This causes autocorrelated returns within a fold, which inflates bootstrap P(mean>0).

### Fix: Minimum Gap = 2 × horizon
```python
# In build_events(), change:
idx = dedup_idx(x["entry"], horizon)
# To:
idx = dedup_idx(x["entry"], gap=2 * horizon)
```

**Impact:** This will reduce `n` (fewer trades), but the remaining trades will have independent returns. The reduction in n is the honest cost of this fix. If a hypothesis loses its PASS classification after this fix, the original PASS was partially inflated.

**Action required:** Re-run all currently PASS hypotheses (H32, H33, H59, H60, H76, H77, H78, H79, H81, H82) with `gap=2*horizon` to check which retain PASS status.

---

## 7. Gap 6: True Hold-Out OOS Block

### The Problem
In the current 60/15/15 WF, all data is used in either training or test folds. There is no data that has been completely untouched. The final classification decision is made after looking at WF results, which means the classification itself is a form of in-sample selection.

### Fix: Reserve a Final 30-Day Block
When data is extended to 2+ years:
1. Reserve the **most recent 30 days** as a permanently locked hold-out.
2. Run all WF training/testing on the preceding data only.
3. When a hypothesis achieves PASS in WF, run it **once** on the hold-out block and record the result.
4. The hold-out result is never used to tune — it is purely a final integrity check.

**Protocol:**
```
Total data: 2 years (e.g., Feb 2024 – Feb 2026)
Research data: Feb 2024 – Jan 2026 (23 months) — all WF training/testing here
Hold-out: Feb 2026 (most recent 30 days) — locked, never touched until PASS achieved
```

Once a hypothesis is promoted to paper trading, its hold-out performance is the last pre-live validation check.

---

## 8. Gap 7: Regime-Conditional Performance Check

### The Problem
A hypothesis might PASS overall but only work during bull markets, or only during high-volatility regimes. If deployed in the wrong regime, it underperforms or loses.

### Fix: Segment WF Results by Regime
After WF is computed, split the test folds by a regime label (e.g., BTC trend state, RV level) and check if mean returns are consistent across regime types:

```python
# Simple regime segmentation:
# For each test fold, compute the average BTC return during that period
# to classify as bull/bear/sideways

def fold_regime(events_in_fold: pd.DataFrame, threshold: float = 0.03) -> str:
    if events_in_fold.empty:
        return "unknown"
    # Proxy: aggregate forward return direction in fold
    total = events_in_fold["gross_r"].mean()
    if total > threshold:
        return "bull"
    elif total < -threshold:
        return "bear"
    return "sideways"
```

Report: "H32 PASS in 5/7 folds; of the 5 positive folds, 3 were bull regime, 2 were sideways. Of the 2 negative folds, both were bear regime." This tells you whether the signal is regime-dependent.

---

## 9. Updated Classification Criteria (Proposed)

Current gate passes if:
- `n >= 50`, `folds >= 5`
- `baseline mean > 0 AND CI_low > 0`
- `wf mean > 0 AND pos_fold_pct >= 60% AND wf CI_low > 0`

**Proposed enhanced gate (add all of the above):**
- `n >= 100` (raise minimum sample from 50) — more reliable estimates
- `WF Sharpe > 0.5` after friction — risk-adjusted quality
- `MAE median > -0.005` — executable live
- `Permutation test p < 0.10` — timing carries information (softer threshold)
- `Survives BH-FDR at α=0.10` within batch — false discovery protection (softer threshold within batch)

A hypothesis that passes all enhanced gates with margin gets PASS. A hypothesis that passes the original gates but fails one enhanced gate gets BORDERLINE. Two or more enhanced gate failures → FAIL.

---

## 9b. Recency Weighting in Bootstrap and WF

### The Problem
WF folds from 4 months ago receive equal weight to folds from last week in the aggregate mean. In crypto, older folds may reflect entirely different microstructure (pre- vs post-ETF, different volatility regime). Equally weighting all history can dilute or obscure the current signal quality.

### Fix Option A: Require Recent Fold Pass
Add a gate: the **2 most recent WF test folds must both be positive** for a PASS classification. A hypothesis that was positive 5 months ago but negative in the last 30 days should not get a PASS.

```python
# In classify_mode(), after computing positive_fold_pct:
sorted_folds = sorted(wf_mode["folds"], key=lambda f: f["test_start"], reverse=True)
recent_two = [f["mean"] for f in sorted_folds[:2] if f.get("n", 0) > 0]
recent_both_positive = len(recent_two) == 2 and all(m > 0 for m in recent_two)
# Require recent_both_positive=True for final PASS (not just BORDERLINE)
```

### Fix Option B: Exponential Decay Weighting in Bootstrap
Weight recent trades more heavily in the bootstrap to reflect their greater relevance:

```python
def bootstrap_mean_stats_weighted(
    values: np.ndarray,
    timestamps: np.ndarray,  # unix timestamps of each trade
    iters: int,
    seed: int,
    half_life_days: float = 60.0,
    ci: float = 0.95,
) -> dict:
    x = np.asarray(values, dtype=float)
    t = np.asarray(timestamps, dtype=float)
    finite = np.isfinite(x)
    x, t = x[finite], t[finite]
    n = len(x)
    if n == 0:
        return {"mean_ci_low": 0.0, "mean_ci_high": 0.0, "p_mean_gt_0": 0.0}
    # Exponential decay: trades from half_life_days ago count 50% as much
    decay = np.log(2) / (half_life_days * 86400)
    t_max = t.max()
    weights = np.exp(-decay * (t_max - t))
    weights /= weights.sum()
    rng = np.random.default_rng(seed)
    samples = rng.choice(x, size=(iters, n), replace=True, p=weights)
    means = samples.mean(axis=1)
    alpha = (1.0 - ci) / 2.0
    return {
        "mean_ci_low": float(np.quantile(means, alpha)),
        "mean_ci_high": float(np.quantile(means, 1.0 - alpha)),
        "p_mean_gt_0": float((means > 0).mean()),
    }
```

**Recommendation:** Start with Option A (simpler, no interface change). Add Option B when data is extended to 12 months.

---

## 10. Implementation Priority

| Fix | Impact | Effort | Do When |
|-----|--------|--------|---------|
| Trade independence (2×horizon gap) | HIGH — affects all current PASSes | LOW | Immediately |
| Sharpe ratio in WF | HIGH — improves classification quality | LOW-MEDIUM | Next pipeline update |
| BH-FDR correction | HIGH — prevents false discoveries | LOW | Next batch run |
| Permutation test | MEDIUM — validates signal timing | MEDIUM | After perf optimization |
| MAE gate | MEDIUM — improves live executability | LOW | Next pipeline update |
| Hold-out OOS block | HIGH — final integrity check | LOW (once data extended) | After data extension |
| Regime conditional check | MEDIUM — reveals fragility | MEDIUM | After data extension |

---

## 11. Links to Related Documents
- `RESEARCH_ROADMAP.md` — strategic direction and new signal families
- `PERFORMANCE_OPTIMIZATION.md` — how to speed up the pipeline before adding more tests
- `AI_AGENT.md` — current operating brief and locked hypothesis state
