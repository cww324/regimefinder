# Performance Optimization
**Created:** 2026-02-22
**Status:** Active — describes current bottlenecks and proposed fixes for the research pipeline.

---

## 1. Current Performance Profile

**Observed behavior:** >1 hour per batch run, 99% single-core CPU utilization.

The pipeline runs each hypothesis 3 times sequentially (once per cost mode: gross, bps8, bps10), each as a separate subprocess that:
1. Starts a new Python interpreter
2. Re-imports all modules
3. Re-loads and re-computes the full feature frame from scratch
4. Runs signal generation, WF, and bootstrap
5. Writes JSON output and exits

The bottleneck is not disk I/O or bootstrap — it is the feature computation in `load_frame()`, which is re-run 3 times per hypothesis.

---

## 2. Root Cause: `pct_rank_last` via `rolling().apply(raw=False)`

The dominant bottleneck is in `scripts/research_family_runner.py`, the `load_frame()` function.

### The offending pattern:
```python
def pct_rank_last(window: pd.Series) -> float:
    s = pd.Series(window)
    return float(s.rank(pct=True).iloc[-1])
```

This is called via `rolling(window).apply(pct_rank_last, raw=False)` approximately **10+ times** per `load_frame()` call:

```python
# In load_frame() — each line below is O(n * window) with Python overhead:
h1["spread_pct"] = h1["spread"].rolling(2000).apply(pct_rank_last, raw=False)    # on 1h data
x["ret1_abs_btc_pct"] = x["ret1_abs_btc"].rolling(w20d).apply(pct_rank_last, raw=False)  # w20d=5760
x["ret1_abs_eth_pct"] = x["ret1_abs_eth"].rolling(w20d).apply(pct_rank_last, raw=False)
x["atr14_pct_btc"]    = x["atr14_btc"].rolling(w20d).apply(pct_rank_last, raw=False)
x["atr14_pct_eth"]    = x["atr14_eth"].rolling(w20d).apply(pct_rank_last, raw=False)
x["rv48_pct_btc"]     = x["rv48_btc"].rolling(w20d).apply(pct_rank_last, raw=False)
x["rv48_pct_eth"]     = x["rv48_eth"].rolling(w20d).apply(pct_rank_last, raw=False)
x["atr_rv_ratio_pct_btc"] = atr_rv_ratio.rolling(w20d).apply(pct_rank_last, raw=False)
x["atr_rv_pct_ratio_pct"] = atr_rv_pct_ratio.rolling(w20d).apply(pct_rank_last, raw=False)
x["abs_vwap_dist_pct_btc"] = (...).rolling(w20d).apply(pct_rank_last, raw=False)
x["abs_delta_er_pct"] = (...).rolling(w20d).apply(pct_rank_last, raw=False)
```

**The cost per call:** With `n=51,000` bars and `w20d=5760`:
- `rolling().apply(raw=False)` creates a Python `pd.Series` object for **every single window position**
- For each Series, it runs a full sort-based rank operation
- ~45,000 valid windows × 10+ columns = ~450,000 full rank operations per `load_frame()` call
- Called 3 times per hypothesis = **1.35 million rank operations per hypothesis**

This runs entirely on a single Python thread with no vectorization.

### The fix: Vectorized rolling percentile rank

The percentile rank of the last value in a rolling window can be computed as:
`rank = (number of values in window <= current value) / window size`

This is equivalent to `rolling().apply(pct_rank_last)` but can be computed using pandas' built-in `rolling().rank()` method (pandas >= 1.4.0):

```python
# SLOW (current):
x["rv48_pct_btc"] = x["rv48_btc"].rolling(w20d).apply(pct_rank_last, raw=False)

# FAST (replacement):
x["rv48_pct_btc"] = x["rv48_btc"].rolling(w20d).rank(pct=True)
```

`rolling().rank(pct=True)` is implemented in Cython and runs approximately **20–100x faster** than the Python-callback version for large windows.

**Apply this replacement to all 10+ `pct_rank_last` call sites in `load_frame()`.**

Note: `rolling().rank()` was added in pandas 1.4. Verify the installed pandas version supports it:
```bash
.venv/bin/python -c "import pandas; print(pandas.__version__)"
```
If pandas < 1.4, upgrade: `.venv/bin/pip install --upgrade pandas`

---

## 3. Root Cause 2: Frame Computed 3× Per Hypothesis (Subprocess Architecture)

### Current flow:
```
run_hypothesis_batch.py
  for mode in ['gross', 'bps8', 'bps10']:
    subprocess → research_family_runner.py --cost-mode gross  → load_frame() → signal → WF → JSON
    subprocess → research_family_runner.py --cost-mode bps8   → load_frame() → signal → WF → JSON
    subprocess → research_family_runner.py --cost-mode bps10  → load_frame() → signal → WF → JSON
```

The frame is **identical** across all 3 modes — only the cost deducted from gross_r changes. So 2/3 of all `load_frame()` computation is pure waste.

### The fix: Single-process multi-mode execution

Restructure `research_family_runner.py` so that when called without `--cost-mode` (or with `--all-modes`), it:
1. Calls `load_frame()` once
2. Calls `build_events()` once
3. Calls `compute_for_cost()` three times (cheap — just arithmetic on the already-computed events)
4. Writes a single JSON with all three mode results

```python
# Proposed interface change in research_family_runner.py:
# Add: --all-modes flag (runs gross + bps8 + bps10 in one process)

def main_all_modes(args):
    events = build_events(...)  # called ONCE
    results = {}
    for mode in ['gross', 'bps8', 'bps10']:
        cost = cost_value(mode)
        baseline, wf, diag = compute_for_cost(events, cost, ...)
        results[mode] = {"baseline": baseline, "wf": wf, "diagnostics": diag}
    # write single combined JSON
```

Then in `run_hypothesis_batch.py`, replace the 3-subprocess loop with a single subprocess call using `--all-modes`.

**Expected speedup:** 3× reduction in `load_frame()` calls alone, plus elimination of 2× Python interpreter startup overhead.

---

## 4. Secondary Bottleneck: MAE Loop in Python

In `build_events()` at line ~1055, there is a Python `for` loop over signal entry indices:

```python
for i in idx:
    i = int(i)
    direction = sig_arr[i]
    ...
    path = (close_arr[ent_i + 1 : ex_i + 1] / ep - 1.0) * direction
    mae_vals.append(float(np.min(finite_path)))
```

For hypotheses with many signals (n > 500), this loop adds measurable overhead. It can be vectorized using numpy:

```python
# Vectorized MAE (for fixed horizon only — the common case):
def compute_mae_vectorized(
    close_arr: np.ndarray,
    entry_indices: np.ndarray,
    direction_arr: np.ndarray,
    horizon: int,
    entry_offset: int = 0,
) -> np.ndarray:
    n = len(entry_indices)
    mae = np.full(n, np.nan)
    for k, i in enumerate(entry_indices):
        ent_i = i + entry_offset
        ex_i = ent_i + horizon
        if ent_i < 0 or ex_i >= len(close_arr):
            continue
        ep = close_arr[ent_i]
        if not np.isfinite(ep) or ep == 0:
            continue
        path = (close_arr[ent_i + 1:ex_i + 1] / ep - 1.0) * direction_arr[i]
        finite = path[np.isfinite(path)]
        if finite.size:
            mae[k] = float(np.min(finite))
    return mae
```

For truly variable horizons, a fully vectorized approach requires more work (padded arrays). The loop version above is acceptable for now but can be Cythonized or numba-JIT'd if needed.

---

## 5. Bootstrap Optimization

The bootstrap is run with `iters=3000` per cost mode, and per WF fold aggregate. With 3 modes and multi-fold WF, total bootstrap iterations per hypothesis is approximately:
- Baseline: 3 × 3000 = 9,000
- WF aggregate: 3 × 3000 = 9,000
- Total: ~18,000 bootstrap draws per hypothesis

At 3000 iterations with n=200-500 trades, each bootstrap is fast individually, but they accumulate. Two options:
1. **Reduce to 1000 iterations** for hypothesis screening; use 3000 only for final PASS candidates
2. **Use `numpy` strided tricks** for faster resampling (preallocate the sample matrix)

The current implementation already uses `rng.choice(x, size=(iters, n), replace=True)` which is already vectorized. The bottleneck is not here — optimize `load_frame()` first.

---

## 6. Parallelization Strategy

Once the single-process multi-mode fix is in place, parallelizing across hypotheses becomes straightforward.

### Option A: Parallel hypothesis batch (multiprocessing)
```python
# In run_hypothesis_batch.py:
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor(max_workers=4) as pool:
    futures = {
        pool.submit(run_one_hypothesis, hyp_id, hyp_def, dataset_defaults, gates, dsn): hyp_id
        for hyp_id in batch_ids
    }
    for future in futures:
        result = future.result()
```

**Caveat:** Each subprocess will call `load_frame()` independently. With 4 workers, you'd have 4 concurrent frame loads. On a system with enough RAM (frame is ~50–100 MB), this is fine.

### Option B: Shared frame (shared memory)
Pre-compute the frame in the main process, write to a temp file or shared memory, and pass the path to worker processes which load from the cache. This avoids 4× `load_frame()` computation:

```python
# In main process:
frame = load_frame(days=180, dsn=dsn)
frame.to_parquet("/tmp/rc_frame_cache.parquet")

# In worker:
frame = pd.read_parquet("/tmp/rc_frame_cache.parquet")
events = build_events_from_frame(frame, hypothesis_id, ...)
```

**Recommendation:** Start with Option A (simpler). Move to Option B if RAM or CPU is the bottleneck.

---

## 7. Profiling Instructions

Before making changes, confirm the bottleneck profile:

```bash
# Profile a single hypothesis run to see where time is spent:
PYTHONPATH=. .venv/bin/python -m cProfile -o /tmp/profile.out \
  scripts/research_family_runner.py \
  --hypothesis-id H32 \
  --family cross_asset_regime \
  --days 180 \
  --cost-mode gross \
  --wf 60 15 15 \
  --bootstrap-iters 3000 \
  --output-json /tmp/h32_profile_test.json \
  --dsn "$RC_DB_DSN"

# View top functions by cumulative time:
PYTHONPATH=. .venv/bin/python -c "
import pstats, io
p = pstats.Stats('/tmp/profile.out', stream=io.StringIO())
p.sort_stats('cumulative')
p.print_stats(20)
print(p.stream.getvalue())
"
```

This will confirm that `apply` + `pct_rank_last` dominate the profile before spending time on fixes.

---

## 8. Implementation Order and Expected Speedup

| Fix | Effort | Expected Speedup | Risk |
|-----|--------|-----------------|------|
| Replace `pct_rank_last` with `rolling().rank(pct=True)` | LOW (10 line changes) | 10–50× on `load_frame()` | Low — behavior-equivalent |
| Single-process multi-mode (eliminate 2/3 subprocess launches) | MEDIUM (refactor runner interface) | 3× on total hypothesis time | Medium — requires interface change |
| Parallel hypothesis batch (4 workers) | MEDIUM | 4× on batch throughput | Medium — requires process-safe DB access |
| Frame caching (shared parquet) | MEDIUM | Additional 4× vs Option A | Low once Option A works |
| Vectorize MAE loop | LOW | 5–20% on `build_events()` | Low |

**Realistic total speedup after all fixes:** 50–100× reduction in wall-clock time. A batch that takes 1 hour today should take 1–2 minutes.

---

## 9. Testing After Optimization

After any change to `load_frame()` or `build_events()`, verify:

1. **Reproducibility:** Run the same hypothesis before and after the change. `gross_r` values for each trade must be identical.
2. **Artifact consistency:** `logic_hash` in the artifact JSON must match pre-change runs.
3. **Run existing tests:** `python -m pytest tests/` must pass with zero failures.
4. **Spot-check pct ranks:** For a known bar, compare `rolling().rank(pct=True)` result vs manual calculation.

### Quick regression test:
```bash
# Run H32 before optimization, save output:
PYTHONPATH=. .venv/bin/python scripts/research_family_runner.py \
  --hypothesis-id H32 --family cross_asset_regime \
  --days 180 --cost-mode gross --wf 60 15 15 \
  --bootstrap-iters 100 --seed 42 \
  --output-json /tmp/h32_before.json --dsn "$RC_DB_DSN"

# After optimization, run again:
PYTHONPATH=. .venv/bin/python scripts/research_family_runner.py \
  --hypothesis-id H32 --family cross_asset_regime \
  --days 180 --cost-mode gross --wf 60 15 15 \
  --bootstrap-iters 100 --seed 42 \
  --output-json /tmp/h32_after.json --dsn "$RC_DB_DSN"

# Compare baseline n and mean — must be identical:
python -c "
import json
b = json.load(open('/tmp/h32_before.json'))
a = json.load(open('/tmp/h32_after.json'))
bm = b['baseline']['gross']
am = a['baseline']['gross']
assert bm['n'] == am['n'], f'n mismatch: {bm[\"n\"]} vs {am[\"n\"]}'
assert abs(bm['mean'] - am['mean']) < 1e-10, f'mean mismatch: {bm[\"mean\"]} vs {am[\"mean\"]}'
print('Regression check PASSED')
"
```

---

## 10. Links to Related Documents
- `RESEARCH_ROADMAP.md` — strategic direction (add new signals only after pipeline is fast)
- `VALIDATION_IMPROVEMENTS.md` — additional tests to add once pipeline is optimized
- `AI_AGENT.md` — current operating brief
