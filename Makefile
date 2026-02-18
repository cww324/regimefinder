PYTHON := PYTHONPATH=. .venv/bin/python

.PHONY: batch status

batch:
	$(PYTHON) scripts/run_hypothesis_batch.py

status:
	$(PYTHON) scripts/render_summary_report.py
