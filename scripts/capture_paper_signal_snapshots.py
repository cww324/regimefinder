import argparse
import json
from datetime import timedelta

from app.db import rc
from app.strategy.trend import trend_regime


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Capture signal-time snapshots for rc paper positions.")
    p.add_argument("--dsn", required=True, help="Postgres DSN")
    p.add_argument("--position-id", type=int, default=0, help="Optional single position_id")
    p.add_argument("--timeframe", default="5m", choices=["5m"], help="Snapshot timeframe")
    p.add_argument("--signal-offset-sec", type=int, default=300, help="Signal timestamp = entry_ts - offset")
    p.add_argument("--force", action="store_true", help="Rebuild even if snapshot exists")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    with rc.connect(args.dsn) as conn:
        tf_id = rc.get_timeframe_id(conn, args.timeframe)

        where = ["p.opened_at IS NOT NULL"]
        params: list[object] = []
        if args.position_id:
            where.append("p.position_id = %s")
            params.append(args.position_id)
        if not args.force:
            where.append("ss.position_id IS NULL")

        where_sql = " AND ".join(where)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    p.position_id,
                    p.hypothesis_pk,
                    p.symbol_id,
                    p.opened_at,
                    (p.opened_at - make_interval(secs => %s)) AS signal_ts
                FROM rc.paper_positions p
                LEFT JOIN rc.paper_signal_snapshots ss ON ss.position_id = p.position_id
                WHERE {where_sql}
                ORDER BY p.position_id
                """,
                tuple([args.signal_offset_sec, *params]),
            )
            positions = cur.fetchall()

        created = 0
        skipped = 0
        for position_id, hypothesis_pk, symbol_id, opened_at, signal_ts in positions:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.open, c.high, c.low, c.close, c.volume
                    FROM rc.candles c
                    WHERE c.symbol_id = %s
                      AND c.timeframe_id = %s
                      AND c.ts = %s
                    """,
                    (symbol_id, tf_id, signal_ts),
                )
                candle = cur.fetchone()
                if not candle:
                    skipped += 1
                    continue

                cur.execute(
                    """
                    SELECT
                        MAX(CASE WHEN f.feature_name = 'atr14' THEN f.feature_value END) AS atr14,
                        MAX(CASE WHEN f.feature_name = 'er20' THEN f.feature_value END) AS er20,
                        MAX(CASE WHEN f.feature_name = 'rv48' THEN f.feature_value END) AS rv48,
                        MAX(CASE WHEN f.feature_name = 'vwap48' THEN f.feature_value END) AS vwap48
                    FROM rc.features f
                    WHERE f.symbol_id = %s
                      AND f.timeframe_id = %s
                      AND f.ts = %s
                      AND f.feature_version = 'v1'
                    """,
                    (symbol_id, tf_id, signal_ts),
                )
                feat = cur.fetchone()

                atr14 = float(feat[0]) if feat and feat[0] is not None else None
                er20 = float(feat[1]) if feat and feat[1] is not None else None
                rv48 = float(feat[2]) if feat and feat[2] is not None else None
                vwap48 = float(feat[3]) if feat and feat[3] is not None else None
                regime = trend_regime(er20) if er20 is not None else None

                metadata = {
                    "source": "capture_paper_signal_snapshots",
                    "signal_offset_sec": args.signal_offset_sec,
                }

                cur.execute(
                    """
                    INSERT INTO rc.paper_signal_snapshots (
                        position_id,
                        hypothesis_pk,
                        symbol_id,
                        timeframe_id,
                        signal_ts,
                        entry_ts,
                        signal_open,
                        signal_high,
                        signal_low,
                        signal_close,
                        signal_volume,
                        atr14,
                        er20,
                        rv48,
                        vwap48,
                        regime,
                        metadata,
                        updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s::jsonb, NOW()
                    )
                    ON CONFLICT (position_id)
                    DO UPDATE SET
                        hypothesis_pk = EXCLUDED.hypothesis_pk,
                        symbol_id = EXCLUDED.symbol_id,
                        timeframe_id = EXCLUDED.timeframe_id,
                        signal_ts = EXCLUDED.signal_ts,
                        entry_ts = EXCLUDED.entry_ts,
                        signal_open = EXCLUDED.signal_open,
                        signal_high = EXCLUDED.signal_high,
                        signal_low = EXCLUDED.signal_low,
                        signal_close = EXCLUDED.signal_close,
                        signal_volume = EXCLUDED.signal_volume,
                        atr14 = EXCLUDED.atr14,
                        er20 = EXCLUDED.er20,
                        rv48 = EXCLUDED.rv48,
                        vwap48 = EXCLUDED.vwap48,
                        regime = EXCLUDED.regime,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    (
                        position_id,
                        hypothesis_pk,
                        symbol_id,
                        tf_id,
                        signal_ts,
                        opened_at,
                        float(candle[0]),
                        float(candle[1]),
                        float(candle[2]),
                        float(candle[3]),
                        float(candle[4]),
                        atr14,
                        er20,
                        rv48,
                        vwap48,
                        regime,
                        json.dumps(metadata, sort_keys=True),
                    ),
                )
                created += 1

        conn.commit()

    print(f"snapshots_upserted={created}")
    print(f"positions_skipped_no_signal_candle={skipped}")


if __name__ == "__main__":
    main()
