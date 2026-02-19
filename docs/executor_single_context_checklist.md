# Executor Single-Context Checklist

Purpose: prevent mixed runtime/network contexts during batch execution with Postgres.

## Rule

For any `make batch` run that depends on `RC_DB_DSN`, Executor must perform precheck and execution in the exact same shell session.

## Required Steps (Same Shell Only)

1. Export DSN explicitly:
   - `export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'`
2. Run connectivity probe:
   - `python - <<'PY'`
   - `import os, psycopg`
   - `with psycopg.connect(os.environ["RC_DB_DSN"]) as c:`
   - `    with c.cursor() as cur:`
   - `        cur.execute("select 1")`
   - `        print(cur.fetchone())`
   - `PY`
3. Without opening a new shell or switching context, run:
   - `make batch`

## Failure Handling

- If probe fails: stop and report (do not run batch).
- If batch fails: write/confirm `results/errors/<timestamp>_<hyp>.json`, stop immediately.
- Do not run a retry from a different shell/context.

## Notes

- This checklist is operational guidance and does not replace `AGENTS.md`.
- `AGENTS.md` queue rules still apply (batch size, stop-on-first-error, next_index handling).
