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

-- Bybit perpetual futures venue (data-source only; no trading)
INSERT INTO rc.venues (venue_code, venue_name, metadata)
VALUES (
    'bybit_futures',
    'Bybit Perpetual Futures',
    '{"type": "perp_futures", "data_use": "research_signals_only", "auth_required": false}'::jsonb
)
ON CONFLICT (venue_code) DO UPDATE
SET venue_name = EXCLUDED.venue_name,
    metadata   = EXCLUDED.metadata;

-- 8h timeframe for funding rate / OI settlement cadence
INSERT INTO rc.timeframes (timeframe_code, seconds)
VALUES ('8h', 28800)
ON CONFLICT (timeframe_code) DO UPDATE
SET seconds = EXCLUDED.seconds;

-- Bybit perp symbols (USDT-margined; price ≈ USD for signal purposes)
WITH v AS (
    SELECT venue_id FROM rc.venues WHERE venue_code = 'bybit_futures'
)
INSERT INTO rc.symbols (venue_id, symbol_code, base_asset, quote_asset, status, metadata)
SELECT
    v.venue_id,
    x.symbol_code,
    x.base_asset,
    x.quote_asset,
    'active',
    '{"instrument_type": "perpetual_future", "margin_asset": "USDT"}'::jsonb
FROM v
JOIN (
    VALUES
        ('BTCUSDT', 'BTC', 'USDT'),
        ('ETHUSDT', 'ETH', 'USDT')
) AS x(symbol_code, base_asset, quote_asset) ON TRUE
ON CONFLICT (venue_id, symbol_code) DO UPDATE
SET
    base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    status     = EXCLUDED.status,
    metadata   = EXCLUDED.metadata;

-- Hyperliquid perpetual DEX venue (1h funding settlements, data-source only)
INSERT INTO rc.venues (venue_code, venue_name, metadata)
VALUES (
    'hyperliquid',
    'Hyperliquid Perpetual DEX',
    '{"type": "perp_dex", "data_use": "research_signals_only", "auth_required": false, "funding_cadence": "1h"}'::jsonb
)
ON CONFLICT (venue_code) DO UPDATE
SET venue_name = EXCLUDED.venue_name,
    metadata   = EXCLUDED.metadata;

-- 1h timeframe for Hyperliquid funding settlement cadence
INSERT INTO rc.timeframes (timeframe_code, seconds)
VALUES ('1h', 3600)
ON CONFLICT (timeframe_code) DO UPDATE
SET seconds = EXCLUDED.seconds;

-- Hyperliquid symbols (coin names match Hyperliquid's API naming)
WITH v AS (
    SELECT venue_id FROM rc.venues WHERE venue_code = 'hyperliquid'
)
INSERT INTO rc.symbols (venue_id, symbol_code, base_asset, quote_asset, status, metadata)
SELECT
    v.venue_id,
    x.symbol_code,
    x.base_asset,
    x.quote_asset,
    'active',
    '{"instrument_type": "perpetual_future", "margin_asset": "USDC"}'::jsonb
FROM v
JOIN (
    VALUES
        ('BTC', 'BTC', 'USD'),
        ('ETH', 'ETH', 'USD')
) AS x(symbol_code, base_asset, quote_asset) ON TRUE
ON CONFLICT (venue_id, symbol_code) DO UPDATE
SET
    base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    status     = EXCLUDED.status,
    metadata   = EXCLUDED.metadata;

-- Gate.io perpetual futures venue (OI + liquidations data source; US-accessible)
INSERT INTO rc.venues (venue_code, venue_name, metadata)
VALUES (
    'gate_futures',
    'Gate.io Perpetual Futures',
    '{"type": "perp_futures", "data_use": "research_signals_only", "auth_required": false, "oi_cadence": "1h", "liq_cadence": "1h"}'::jsonb
)
ON CONFLICT (venue_code) DO UPDATE
SET venue_name = EXCLUDED.venue_name,
    metadata   = EXCLUDED.metadata;

-- Gate.io perp symbols (USDT-margined; symbol_code matches Hyperliquid short names for loader compat)
WITH v AS (
    SELECT venue_id FROM rc.venues WHERE venue_code = 'gate_futures'
)
INSERT INTO rc.symbols (venue_id, symbol_code, base_asset, quote_asset, status, metadata)
SELECT
    v.venue_id,
    x.symbol_code,
    x.base_asset,
    x.quote_asset,
    'active',
    '{"instrument_type": "perpetual_future", "margin_asset": "USDT", "gate_contract": "BTC_USDT"}'::jsonb
FROM v
JOIN (
    VALUES
        ('BTC', 'BTC', 'USDT'),
        ('ETH', 'ETH', 'USDT')
) AS x(symbol_code, base_asset, quote_asset) ON TRUE
ON CONFLICT (venue_id, symbol_code) DO UPDATE
SET
    base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    status     = EXCLUDED.status,
    metadata   = EXCLUDED.metadata;

COMMIT;
