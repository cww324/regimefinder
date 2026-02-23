# BEST_HYPOTHESES.md
**Last Updated:** 2026-02-23
**Dataset:** 365 days (Feb 2025 – Feb 2026), ~105k bars/symbol, 60/15/15 WF (~20 folds)

Quick reference for the best confirmed hypotheses. Full results in `FINDINGS_365D.md`.

---

## Tier 1: Perfect (20/20 WF folds at both gross and bps8)

| ID | Signal | gross mean/trade | WF gross | WF bps8 | Notes |
|----|--------|-----------------|----------|---------|-------|
| **H65** | ETH slope flip, horizon=8 | +0.34% | 20/20 | 20/20 | Core signal — best single hypothesis |
| **H84** | H65, 08:00–16:00 UTC only | +0.38% | 20/20 | 20/20 | Strongest variant — EU/US overlap session |
| **H67** | H65, 120d lookback replication | +0.34% | 20/20 | 20/20 | Confirms H65 not lookback-sensitive |
| **H73** | H65, 180d lookback replication | +0.34% | 20/20 | 20/20 | Confirms H65 not lookback-sensitive |
| **H77** | H65, next-bar execution realism | +0.34% | 20/20 | 20/20 | Survives 1-bar execution lag |
| **H79** | H65, extra-cost stress | +0.34% | 20/20 | 20/20 | Survives higher cost assumptions |

**What is H65?**
ETH 1h EMA slope flip (direction change) as entry trigger. Trade ETH-USD or BTC-USD (depending on variant)
at bar following slope flip, hold for 8 bars (40 minutes). The signal is: when ETH's hourly trend
changes direction, continue in the direction of the new trend for ~40 minutes.

---

## Tier 2: Strong PASS (WF 19-20/20 gross, 15-19/20 bps8)

| ID | Signal | gross mean/trade | WF gross | WF bps8 | Notes |
|----|--------|-----------------|----------|---------|-------|
| H60 | ETH slope flip, horizon=6 | +0.26% | 20/20 | 18/20 | Slightly shorter horizon than H65 |
| H63 | BTC slope flip, horizon=8 | +0.21% | 20/20 | 19/20 | Same idea, BTC-side signal |
| H76 | H63, next-bar execution realism | +0.21% | 20/20 | 19/20 | H63 survives 1-bar lag |
| H78 | H63, extra-cost stress | +0.21% | 20/20 | 19/20 | H63 survives higher cost |
| H66 | H63, 120d lookback replication | +0.21% | 20/20 | 19/20 | H63 confirmed |
| H70 | H65, odd-day subsample | +0.34% | 20/20 | 19/20 | H65 subsample stability check |
| H72 | H63, 180d replication control | +0.21% | 20/20 | 19/20 | H63 confirmed |
| H83 | H65, 00:00–08:00 UTC | +0.27% | 20/20 | 18/20 | Asia session — better than expected |
| H85 | H65, 16:00–24:00 UTC | +0.36% | 19/20 | 18/20 | US afternoon session strong |
| H68 | H63, odd-day subsample | +0.22% | 19/20 | 19/20 | H63 subsample stability check |
| H59 | BTC slope flip, horizon=6 | +0.16% | 20/20 | 16/20 | Baseline BTC variant |
| H71 | H65, even-day subsample | +0.34% | 19/20 | 18/20 | H65 subsample stability check |
| H75 | H60, 120d replication | +0.26% | 20/20 | 18/20 | H60 confirmed |
| H64 | H60, horizon=4 | +0.17% | 20/20 | 18/20 | Shorter hold |
| H81 | H63, 08:00–16:00 UTC | +0.23% | 20/20 | 17/20 | H63 EU/US window |
| H82 | H63, 16:00–24:00 UTC | +0.22% | 20/20 | 15/20 | H63 US afternoon |
| H74 | H59, 120d replication | +0.16% | 20/20 | 16/20 | H59 confirmed |
| H69 | H63, even-day subsample | +0.20% | 20/20 | 16/20 | H63 subsample check |

---

## Tier 3: PASS (borderline bps8 or smaller sample)

| ID | Signal | gross mean/trade | WF gross | WF bps8 | Notes |
|----|--------|-----------------|----------|---------|-------|
| H99 | Session handoff (UTC open transitions) | +0.20% | 17/20 | 12/20 | Small n=70, marginal bps8 |

---

## Tier 4: BORDERLINE (gross strong, bps8 marginal)

| ID | Signal | gross mean/trade | WF gross | WF bps8 | Notes |
|----|--------|-----------------|----------|---------|-------|
| H39 | cross_asset_regime variant | — | 20/20 | 16/20 | bps10 likely fails |
| H61 | cross_asset_regime variant | — | 20/20 | 13/20 | bps8 inconsistent |

---

## Signal in limbo (gross real, cost-constrained)

| ID | Signal | Gross WF | bps8 WF | Issue | Next step |
|----|--------|----------|---------|-------|-----------|
| H32 | ETH 1h EMA slope regime gate | 12/14 | 8/14 | ~7 trades/day; each trade earns +0.074% but pays 0.080% cost | H124: tighter entry |
| H87 | cross_asset_regime variant | 13/14 | 3/14 | Real gross, cost kills it | Reduce frequency |
| H91 | cross_asset_regime variant | 13/14 | 5/14 | Real gross, cost kills it | Reduce frequency |
| H97 | cross_asset_regime variant | 12/14 | 3/14 | Real gross, cost kills it | Reduce frequency |

---

## Key Observations

1. **One signal family dominates.** All 25 PASSes are `cross_asset_regime` — ETH/BTC slope flip trades.
   The signal is that an ETH hourly trend direction change predicts 40-minute continuation.

2. **H65 is the anchor.** H84 has the highest mean (+0.38%) but is session-restricted (08:00–16:00 UTC).
   H65 runs all hours and is fully replicated across lookback windows, execution lag, and cost stress.

3. **Replication is solid.** H65 has 6 independent replications that all pass (H67, H73, H77, H79, H84, H85).
   This is unusually robust for this research history.

4. **H32 is not dead.** The gross signal is real (12/14 WF folds). It fails on cost at current frequency.
   H124 will test a tighter entry threshold to fix this.

5. **No short-side signals survive 365d.** H33 (short variant of H32) collapses on the full year.
   All 25 PASSes are effectively long-biased. The 365d window (Feb 2025–Feb 2026) was a crypto bull run.

---

## What to do next

- Run **H124**: H32 logic with tighter spread threshold (≥0.97 instead of ≥0.90) to solve cost problem
- Consider **portfolio construction** from H65 + H84 (session-filtered variant)
- Run **RF feature importance** experiment on 365d feature matrix to generate new hypothesis candidates
- See `REGIME_FRAMEWORK.md` for H124+ design rules
