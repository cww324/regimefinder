#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if [[ -z "${RC_DB_DSN:-}" ]]; then
  echo "RC_DB_DSN is not set. Export it in-shell or define it in .env before running batch." >&2
  exit 1
fi

.venv/bin/python - <<'PY'
import os
import psycopg

with psycopg.connect(os.environ["RC_DB_DSN"]) as c:
    with c.cursor() as cur:
        cur.execute("select 1")
        print(cur.fetchone())
PY

if [[ $# -gt 0 ]]; then
  PYTHONPATH=. .venv/bin/python scripts/run_hypothesis_batch.py "$@"
else
  make batch
fi
