# Paper Portfolio Executor Checklist

Use this checklist when running the paper portfolio protocol.

## 1) Startup Compliance

1. Declare role: `Executor`
2. Follow startup read order:
   - `AGENTS.md`
   - `AI_AGENT.md`
   - `results/summary.json` (if exists)
   - latest section of `FINDINGS_TECHNICAL.md`

## 2) Same-Shell DB Preflight (Mandatory)

```bash
export RC_DB_DSN='postgresql://rc_user:wemyss@localhost:5432/regime_crypto'
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["RC_DB_DSN"]) as c:
    with c.cursor() as cur:
        cur.execute("select 1")
        print(cur.fetchone())
PY
```

If preflight fails: stop and report. Do not run paper tests.

## 3) Run Order

Run in this exact order:

1. Standalone paper test, `180d`, all selected candidates.
2. Standalone paper test, `365d`, survivors only.
3. Combined portfolio paper test, `180d`.
4. Combined portfolio paper test, `365d`.

Do not mix windows or reorder phases.

## 4) Execution Consistency Rules

- Same fill model and same cost assumptions across all runs.
- Same risk-control profile across all comparable runs.
- No hypothesis rule changes during protocol execution.
- No manual PASS/FAIL decisions by Executor.

## 5) Required Outputs Per Run

Record and publish:

- command used
- candidate set
- window length (`180d` or `365d`)
- execution mode (`standalone` or `combined`)
- artifact path(s)
- if failed: `results/errors/<timestamp>_<id>.json`

Artifacts must include dataset fingerprint fields:

- `start_ts`
- `end_ts`
- `bar_count`
- `db_path`
- `db_last_modified`

Combined-phase heat evidence to provide for Guardian:

- cross-strategy correlation matrix
- strategy PnL share / concentration table
- family-level weight/contribution summary
- explicit flag if any heat threshold breach is observed

## 6) Failure Policy

- Stop immediately on first failure.
- Write/confirm error artifact.
- Do not continue remaining runs in that phase.
- Report blocker with exact path and traceback summary.

## 7) Handoff After Completion

After each completed phase:

1. Hand off to `Guardian` for audit + summary/findings updates.
2. Wait for Guardian PASS before starting the next phase.
3. Send audited evidence to `Capital_Committee` only after full phase completion.

## 8) Diversification Track (Carry-Forward Checklist)

1. If standalone strength is concentrated in one family, open Architect work to define at least one NEW, distinct signal-family hypothesis track.
2. Do not treat close family variants as diversification-complete.
3. Track diversification progress in operational notes before requesting live-candidate decisions.
