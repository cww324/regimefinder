BEGIN;

INSERT INTO rc.venues (venue_code, venue_name)
VALUES ('coinbase', 'Coinbase Advanced Trade')
ON CONFLICT (venue_code) DO UPDATE
SET venue_name = EXCLUDED.venue_name;

INSERT INTO rc.timeframes (timeframe_code, seconds)
VALUES ('5m', 300)
ON CONFLICT (timeframe_code) DO UPDATE
SET seconds = EXCLUDED.seconds;

WITH v AS (
    SELECT venue_id FROM rc.venues WHERE venue_code = 'coinbase'
)
INSERT INTO rc.symbols (venue_id, symbol_code, base_asset, quote_asset, status)
SELECT v.venue_id, x.symbol_code, x.base_asset, x.quote_asset, 'active'
FROM v
JOIN (
    VALUES
        ('BTC-USD', 'BTC', 'USD'),
        ('ETH-USD', 'ETH', 'USD')
) AS x(symbol_code, base_asset, quote_asset) ON TRUE
ON CONFLICT (venue_id, symbol_code) DO UPDATE
SET
    base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    status = EXCLUDED.status;

COMMIT;
