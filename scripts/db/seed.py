import argparse
from pathlib import Path

try:
    import psycopg
except Exception as err:  # pragma: no cover
    raise SystemExit("psycopg is required for seed script. Install dependencies first.") from err


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply db/seed.sql to Postgres rc schema.")
    p.add_argument("--dsn", required=True, help="Postgres DSN, e.g. postgresql://user:pass@host:5432/db")
    p.add_argument("--seed", default="db/seed.sql", help="Path to seed SQL file")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    sql_path = Path(args.seed)
    sql = sql_path.read_text(encoding="utf-8")
    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print(f"seed_applied={sql_path}")


if __name__ == "__main__":
    main()
