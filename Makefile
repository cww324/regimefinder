PYTHON := PYTHONPATH=. .venv/bin/python

.PHONY: batch status db-seed capture-snapshots

batch:
	$(PYTHON) scripts/run_hypothesis_batch.py

status:
	$(PYTHON) scripts/render_summary_report.py

db-seed:
	$(PYTHON) scripts/db/seed.py --dsn "$(RC_DB_DSN)" --seed db/seed.sql

capture-snapshots:
	$(PYTHON) scripts/capture_paper_signal_snapshots.py --dsn "$(RC_DB_DSN)"
