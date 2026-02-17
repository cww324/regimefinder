# Research State — 2026-02-16

## Data Coverage
- BTC-USD spot, 5m candles
- ~180 days of data
- Range: 2025-08-20 22:55 UTC → 2026-02-16 22:55 UTC

## Hypotheses Tested
- H1: Volatility Compression → Expansion (completed)

## Current Script Structure
- `scripts/hypothesis_studies.py` runs **one hypothesis per execution**
- Requires `--hypothesis` flag
- Outputs a single table and appends results to `FINDINGS.md` and `FINDINGS_TECHNICAL.md`

## Next Planned Step
- Run H2 (Large Shock Continuation)
