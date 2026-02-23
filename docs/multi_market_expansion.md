# Multi-Market Expansion Guide
**Created:** 2026-02-23
**Purpose:** How to add new symbols, exchanges, or asset classes to the hypothesis pipeline.

---

## Current State (2026-02-23)

| Component | Status | Notes |
|-----------|--------|-------|
| DB schema (`rc.*`) | **Multi-asset ready** | `symbol` + `venue` columns throughout |
| `scripts/backfill_5m.py` | **Multi-symbol ready** | `--symbol` flag works for any Coinbase symbol |
| `scripts/compute_features.py` | **Multi-symbol ready** | `--symbol` flag |
| `scripts/research_family_runner.py` | **Hardcoded BTC+ETH** | Primary blocker — see §3 |
| `hypotheses.yaml` | BTC+ETH only | Entry rules reference specific symbols |
| `scripts/run_paper_h32_live.py` | BTC+ETH only | Paper runner is symbol-specific |

**Bottom line:** Adding a third symbol requires one targeted refactor in `research_family_runner.py`
plus new hypotheses. Everything else (DB, backfill, features) already generalizes.

---

## What "Multi-Market" Means Here

Three expansion modes, in order of complexity:

1. **New symbol, same exchange** — e.g. SOL-USD on Coinbase
   - Add to backfill, compute features, write new H-numbers
   - research_family_runner.py needs minor change (see §3)

2. **Same symbols, new exchange** — e.g. BTC-USD on Binance or Kraken
   - Enables cross-exchange divergence (CD family) hypotheses
   - Needs new venue row in `rc.venues`, new backfill source
   - CD family (H102–H113) failed partly because Binance data wasn't available

3. **New asset class** — e.g. equities, FX
   - Same pipeline but different data sources, different regime characteristics
   - Treat as a full new project track — don't mix feature assumptions

---

## Step-by-Step: Adding a New Coinbase Symbol (e.g. SOL-USD)

### Step 1 — Seed the new symbol

```sql
-- db/seed.sql or run directly:
INSERT INTO rc.symbols (symbol, base_asset, quote_asset, venue_id, asset_class)
VALUES ('SOL-USD', 'SOL', 'USD',
        (SELECT id FROM rc.venues WHERE slug='coinbase'), 'crypto')
ON CONFLICT DO NOTHING;
```

### Step 2 — Backfill candles

```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_5m.py \
  --dsn "$RC_DB_DSN" \
  --symbol SOL-USD \
  --days 365
```

### Step 3 — Compute features

```bash
PYTHONPATH=. .venv/bin/python scripts/compute_features.py \
  --dsn "$RC_DB_DSN" \
  --symbol SOL-USD \
  --days 365
```

### Step 4 — Verify data

```bash
PYTHONPATH=. .venv/bin/python scripts/health_report.py \
  --dsn "$RC_DB_DSN" --days 30
```

### Step 5 — Write hypotheses targeting the new symbol

Add to `hypotheses.yaml`:
```yaml
- id: H130
  family: cross_asset_regime
  description: SOL-USD ETH slope flip — same CA-1 logic applied to SOL.
  entry_rules:
    - ETH 1h EMA20 slope sign flip (same as H65).
    - Trade SOL-USD in the direction of the ETH slope change.
  parameters:
    primary_symbol: SOL-USD
    secondary_symbol: ETH-USD
    horizon_bars: 8
```

### Step 6 — Update research_family_runner.py (see §3)

---

## §3 — The Blocker: research_family_runner.py

`load_frame()` in `scripts/research_family_runner.py` currently:
- Hard-queries `BTC-USD` and `ETH-USD` by name
- Computes cross-asset features (spread, delta_er, etc.) assuming exactly these two symbols
- Returns a DataFrame with hardcoded column suffixes `_btc` / `_eth`

### What needs to change

**Minimal change (new symbol variant, same CA logic):**
1. Add `--primary-symbol` and `--secondary-symbol` CLI args
2. In `load_frame()`, replace hardcoded `'BTC-USD'`/`'ETH-USD'` with the CLI args
3. Column naming stays `_primary` / `_secondary` or keep `_btc`/`_eth` for CA family

**Larger change (generalize for any two-asset pair):**
1. Parameterize all `_btc` / `_eth` column suffixes based on symbol slugs
2. Allow hypothesis YAML to specify `primary_symbol` and `secondary_symbol` per-hypothesis
3. `build_signal()` routing uses the per-hypothesis symbol config

**Recommended approach:** Start with the minimal change (new symbol, CA family only).
Full generalization is a bigger refactor — do it when you have a second confirmed signal family
beyond CA.

---

## §4 — Adding a New Exchange (Cross-Exchange Divergence)

The CD family (CD-1 etc.) needs price data from two exchanges for the same symbol.

### DB schema is ready

`rc.venues` already has a `slug` column for distinguishing exchanges:
```sql
SELECT id, slug FROM rc.venues;
-- coinbase | binance | kraken ...
```

`rc.candles` has `venue_id` — so BTC-USD from Coinbase and BTC-USD from Binance can
coexist in the same table.

### What needs to be added

1. **New backfill script for the exchange** — e.g. `scripts/backfill_binance.py`
   - Binance REST API: `GET /api/v3/klines` — no auth, but geo-blocks US IPs
   - Alternative: Kraken (`GET /0/public/OHLC`) — accessible from US
   - Insert into `rc.candles` with the appropriate `venue_id`

2. **New compute_features.py call** — one per venue (or parameterize by venue)

3. **New signal family in research_family_runner.py:**
   - Load BTC candles from both venues
   - Compute price divergence (e.g. Coinbase price / Binance price - 1)
   - Signal: divergence crosses threshold → mean-revert

4. **New hypothesis block** with `signal_group: CD-1` etc.

### Why CD failed on 180d

H102–H113 (cross-exchange divergence) all FAIL because we only had Coinbase data.
The signal assumes we can trade on the exchange that's *lagging*. Without real Binance
data, we're testing noise. **Revisit after adding a second exchange feed.**

---

## §5 — Feature Parity Checklist for New Symbols

When adding a new symbol, verify these features exist in the computed output:

| Feature | Source | Available |
|---------|--------|-----------|
| `rv48_pct_{sym}` | compute_features.py | Yes — parameterized |
| `atr14_pct_{sym}` | compute_features.py | Yes — parameterized |
| `er20_{sym}` | compute_features.py | Yes — parameterized |
| `vwap48` / `vwap_z` | load_frame() | Computed on-the-fly |
| `funding_{sym}_pct` | derivatives.py | BTC+ETH only currently |
| `spread_pct` | load_frame() | Hardcoded BTC-ETH currently |

Features computed in `load_frame()` (on-the-fly, not stored in DB) will need to be
extended when adding a new symbol as a *primary* trade target.

---

## Priority Order

1. **H124** first — test tighter CA+FR variant before adding new symbols
2. **RF experiment** — discover new signal families on existing BTC+ETH data
3. **SOL-USD CA replication** — once CA-1 pattern confirmed on existing pair, test transfer to SOL
4. **Kraken BTC** — add second exchange feed to unlock CD family
5. **Full generalization** of research_family_runner.py — when 2+ confirmed non-CA signal families exist

---

## What to Read Next

- `SIGNAL_REGISTRY.md` — current confirmed signals (CA family)
- `REGIME_FRAMEWORK.md` — H124+ hypothesis design rules
- `docs/rf_experiment_plan.md` — ML-assisted hypothesis discovery on existing feature matrix
- `scripts/research_family_runner.py` — the blocker for multi-market expansion
