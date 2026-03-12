PYTHON := PYTHONPATH=. .venv/bin/python

.PHONY: batch status summary db-seed db-migrate-derivatives backfill-derivatives backfill-oi-liq capture-snapshots

batch:
	$(PYTHON) scripts/run_hypothesis_batch.py

status:
	$(PYTHON) scripts/render_summary_report.py

summary:
	$(PYTHON) scripts/build_summary.py

db-seed:
	$(PYTHON) scripts/db/seed.py --dsn "$(RC_DB_DSN)" --seed db/seed.sql

db-migrate-derivatives:
	docker exec -i rc-postgres psql -U rc_user -d regime_crypto < db/schema.sql

backfill-derivatives:
	$(PYTHON) scripts/backfill_derivatives.py --dsn "$(RC_DB_DSN)" --days 365 --venue hyperliquid --symbols BTC,ETH

backfill-oi-liq:
	$(PYTHON) scripts/backfill_oi_liq_gate.py --dsn "$(RC_DB_DSN)" --days 365

capture-snapshots:
	$(PYTHON) scripts/capture_paper_signal_snapshots.py --dsn "$(RC_DB_DSN)"
