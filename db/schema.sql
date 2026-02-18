-- Regime Crypto unified multi-asset schema (PostgreSQL)
-- Purpose: research + paper trading + governance artifacts in one DB.
-- Notes:
-- 1) All symbol-specific tables key by symbol_id (no BTC/ETH hardcoding).
-- 2) Keep raw candles immutable; use ingest_runs + checksums for lineage.

BEGIN;

CREATE SCHEMA IF NOT EXISTS rc;

-- 1) Reference tables
CREATE TABLE IF NOT EXISTS rc.venues (
    venue_id            BIGSERIAL PRIMARY KEY,
    venue_code          TEXT NOT NULL UNIQUE,       -- e.g. coinbase
    venue_name          TEXT NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rc.symbols (
    symbol_id           BIGSERIAL PRIMARY KEY,
    venue_id            BIGINT NOT NULL REFERENCES rc.venues(venue_id),
    symbol_code         TEXT NOT NULL,              -- e.g. BTC-USD
    base_asset          TEXT NOT NULL,              -- e.g. BTC
    quote_asset         TEXT NOT NULL,              -- e.g. USD
    status              TEXT NOT NULL DEFAULT 'active',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (venue_id, symbol_code)
);

CREATE TABLE IF NOT EXISTS rc.timeframes (
    timeframe_id        SMALLSERIAL PRIMARY KEY,
    timeframe_code      TEXT NOT NULL UNIQUE,       -- e.g. 1m, 5m, 1h
    seconds             INTEGER NOT NULL CHECK (seconds > 0)
);

-- 2) Ingest lineage
CREATE TABLE IF NOT EXISTS rc.ingest_runs (
    ingest_run_id       BIGSERIAL PRIMARY KEY,
    venue_id            BIGINT REFERENCES rc.venues(venue_id),
    source_name         TEXT NOT NULL,              -- api, backfill, replay, etc.
    trigger_type        TEXT NOT NULL DEFAULT 'manual',
    started_at          TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'partial')),
    symbols_count       INTEGER NOT NULL DEFAULT 0,
    rows_inserted       BIGINT NOT NULL DEFAULT 0,
    rows_upserted       BIGINT NOT NULL DEFAULT 0,
    rows_rejected       BIGINT NOT NULL DEFAULT 0,
    checksum_sha256     TEXT,
    error_message       TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3) Market data
CREATE TABLE IF NOT EXISTS rc.candles (
    symbol_id           BIGINT NOT NULL REFERENCES rc.symbols(symbol_id),
    timeframe_id        SMALLINT NOT NULL REFERENCES rc.timeframes(timeframe_id),
    ts                  TIMESTAMPTZ NOT NULL,
    open                NUMERIC(20, 10) NOT NULL,
    high                NUMERIC(20, 10) NOT NULL,
    low                 NUMERIC(20, 10) NOT NULL,
    close               NUMERIC(20, 10) NOT NULL,
    volume              NUMERIC(30, 10) NOT NULL DEFAULT 0,
    vwap                NUMERIC(20, 10),
    trade_count         BIGINT,
    ingest_run_id       BIGINT REFERENCES rc.ingest_runs(ingest_run_id),
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol_id, timeframe_id, ts),
    CHECK (high >= low),
    CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CHECK (volume >= 0)
);

CREATE INDEX IF NOT EXISTS idx_candles_time ON rc.candles (timeframe_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_time_desc ON rc.candles (symbol_id, ts DESC);

-- 4) Derived features
CREATE TABLE IF NOT EXISTS rc.features (
    feature_id          BIGSERIAL PRIMARY KEY,
    symbol_id           BIGINT NOT NULL REFERENCES rc.symbols(symbol_id),
    timeframe_id        SMALLINT NOT NULL REFERENCES rc.timeframes(timeframe_id),
    ts                  TIMESTAMPTZ NOT NULL,
    feature_name        TEXT NOT NULL,
    feature_version     TEXT NOT NULL DEFAULT 'v1',
    feature_value       DOUBLE PRECISION NOT NULL,
    source_run_id       BIGINT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol_id, timeframe_id, ts, feature_name, feature_version)
);

CREATE INDEX IF NOT EXISTS idx_features_lookup ON rc.features (symbol_id, timeframe_id, feature_name, ts DESC);

-- 5) Hypothesis catalog
CREATE TABLE IF NOT EXISTS rc.hypotheses (
    hypothesis_pk       BIGSERIAL PRIMARY KEY,
    hypothesis_id       TEXT NOT NULL,              -- e.g. H32
    version             INTEGER NOT NULL DEFAULT 1,
    class               TEXT NOT NULL CHECK (class IN ('tradeable_hypothesis', 'structural_diagnostic')),
    status              TEXT NOT NULL,              -- planned/frozen/etc.
    family              TEXT NOT NULL,
    yaml_hash_sha256    TEXT NOT NULL,
    yaml_snapshot       JSONB NOT NULL,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (hypothesis_id, version)
);

CREATE INDEX IF NOT EXISTS idx_hypotheses_id_status ON rc.hypotheses (hypothesis_id, status);

-- 6) Research run tracking
CREATE TABLE IF NOT EXISTS rc.research_runs (
    run_id                      BIGSERIAL PRIMARY KEY,
    hypothesis_pk               BIGINT NOT NULL REFERENCES rc.hypotheses(hypothesis_pk),
    run_kind                    TEXT NOT NULL CHECK (run_kind IN ('batch', 'manual', 'replay')),
    execution_role              TEXT NOT NULL CHECK (execution_role IN ('executor', 'guardian', 'system')),
    started_at                  TIMESTAMPTZ NOT NULL,
    completed_at                TIMESTAMPTZ,
    status                      TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'partial')),
    queue_batch_id              TEXT,
    command_text                TEXT,
    code_commit                 TEXT,
    config_hash_sha256          TEXT,
    dataset_symbols             JSONB NOT NULL,
    dataset_timeframe           TEXT NOT NULL,
    dataset_start_ts            TIMESTAMPTZ,
    dataset_end_ts              TIMESTAMPTZ,
    dataset_bar_count           BIGINT,
    dataset_db_path             JSONB,
    dataset_db_last_modified    JSONB,
    error_message               TEXT,
    metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_runs_hyp_created ON rc.research_runs (hypothesis_pk, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON rc.research_runs (status, created_at DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_features_source_run'
    ) THEN
        ALTER TABLE rc.features
            ADD CONSTRAINT fk_features_source_run
            FOREIGN KEY (source_run_id)
            REFERENCES rc.research_runs(run_id)
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

-- 7) Research metrics normalized by cost mode + stage
CREATE TABLE IF NOT EXISTS rc.research_metrics (
    metric_id                BIGSERIAL PRIMARY KEY,
    run_id                   BIGINT NOT NULL REFERENCES rc.research_runs(run_id) ON DELETE CASCADE,
    cost_mode                TEXT NOT NULL CHECK (cost_mode IN ('gross', 'bps8', 'bps10', 'bps12', 'bps15')),
    stage                    TEXT NOT NULL CHECK (stage IN ('baseline', 'walkforward')),
    n                        BIGINT,
    mean                     DOUBLE PRECISION,
    std                      DOUBLE PRECISION,
    ci_low                   DOUBLE PRECISION,
    ci_high                  DOUBLE PRECISION,
    p_mean_gt_0              DOUBLE PRECISION,
    win_rate                 DOUBLE PRECISION,
    positive_folds           INTEGER,
    fold_count               INTEGER,
    positive_fold_pct        DOUBLE PRECISION,
    baseline_status          TEXT,
    wf_status                TEXT,
    final_status             TEXT,
    reason                   TEXT,
    metrics_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, cost_mode, stage)
);

CREATE INDEX IF NOT EXISTS idx_research_metrics_run_mode ON rc.research_metrics (run_id, cost_mode);

-- 8) Artifact registry (JSON files, S3 keys, checksums)
CREATE TABLE IF NOT EXISTS rc.research_artifacts (
    artifact_id              BIGSERIAL PRIMARY KEY,
    run_id                   BIGINT NOT NULL REFERENCES rc.research_runs(run_id) ON DELETE CASCADE,
    artifact_type            TEXT NOT NULL CHECK (artifact_type IN ('run_json', 'audit_json', 'summary_json', 'error_json', 'other')),
    storage_uri              TEXT NOT NULL,      -- local path or s3://...
    sha256                   TEXT NOT NULL,
    bytes                    BIGINT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, artifact_type, storage_uri)
);

CREATE INDEX IF NOT EXISTS idx_research_artifacts_run ON rc.research_artifacts (run_id, created_at DESC);

-- 9) Paper trading
CREATE TABLE IF NOT EXISTS rc.paper_signals (
    signal_id                BIGSERIAL PRIMARY KEY,
    hypothesis_pk            BIGINT NOT NULL REFERENCES rc.hypotheses(hypothesis_pk),
    symbol_id                BIGINT NOT NULL REFERENCES rc.symbols(symbol_id),
    ts                       TIMESTAMPTZ NOT NULL,
    direction                SMALLINT NOT NULL CHECK (direction IN (-1, 1)),
    strength                 DOUBLE PRECISION,
    reason_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedup_key                TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (hypothesis_pk, symbol_id, dedup_key)
);

CREATE INDEX IF NOT EXISTS idx_paper_signals_ts ON rc.paper_signals (symbol_id, ts DESC);

CREATE TABLE IF NOT EXISTS rc.paper_orders (
    order_id                 BIGSERIAL PRIMARY KEY,
    signal_id                BIGINT REFERENCES rc.paper_signals(signal_id),
    venue_id                 BIGINT NOT NULL REFERENCES rc.venues(venue_id),
    symbol_id                BIGINT NOT NULL REFERENCES rc.symbols(symbol_id),
    client_order_id          TEXT NOT NULL,
    side                     TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type               TEXT NOT NULL CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit')),
    tif                      TEXT,
    qty                      NUMERIC(30, 10) NOT NULL CHECK (qty > 0),
    limit_price              NUMERIC(20, 10),
    stop_price               NUMERIC(20, 10),
    status                   TEXT NOT NULL CHECK (status IN ('created', 'submitted', 'accepted', 'partially_filled', 'filled', 'cancelled', 'rejected')),
    submitted_at             TIMESTAMPTZ,
    venue_order_id           TEXT,
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (venue_id, client_order_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_orders_symbol_status ON rc.paper_orders (symbol_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS rc.paper_fills (
    fill_id                  BIGSERIAL PRIMARY KEY,
    order_id                 BIGINT NOT NULL REFERENCES rc.paper_orders(order_id) ON DELETE CASCADE,
    ts                       TIMESTAMPTZ NOT NULL,
    price                    NUMERIC(20, 10) NOT NULL CHECK (price > 0),
    qty                      NUMERIC(30, 10) NOT NULL CHECK (qty > 0),
    fee                      NUMERIC(20, 10) NOT NULL DEFAULT 0,
    liquidity                TEXT,
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_fills_order_ts ON rc.paper_fills (order_id, ts);

CREATE TABLE IF NOT EXISTS rc.paper_positions (
    position_id              BIGSERIAL PRIMARY KEY,
    hypothesis_pk            BIGINT NOT NULL REFERENCES rc.hypotheses(hypothesis_pk),
    symbol_id                BIGINT NOT NULL REFERENCES rc.symbols(symbol_id),
    side                     TEXT NOT NULL CHECK (side IN ('long', 'short')),
    status                   TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    opened_at                TIMESTAMPTZ NOT NULL,
    closed_at                TIMESTAMPTZ,
    qty                      NUMERIC(30, 10) NOT NULL CHECK (qty > 0),
    avg_entry_price          NUMERIC(20, 10) NOT NULL CHECK (avg_entry_price > 0),
    avg_exit_price           NUMERIC(20, 10),
    realized_pnl             NUMERIC(20, 10),
    unrealized_pnl           NUMERIC(20, 10),
    max_favorable_excursion  NUMERIC(20, 10),
    max_adverse_excursion    NUMERIC(20, 10),
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_positions_open ON rc.paper_positions (status, symbol_id, opened_at DESC);

CREATE TABLE IF NOT EXISTS rc.paper_daily_summary (
    summary_id               BIGSERIAL PRIMARY KEY,
    trade_date               DATE NOT NULL,
    hypothesis_pk            BIGINT NOT NULL REFERENCES rc.hypotheses(hypothesis_pk),
    symbol_id                BIGINT NOT NULL REFERENCES rc.symbols(symbol_id),
    trades_count             INTEGER NOT NULL DEFAULT 0,
    gross_pnl                NUMERIC(20, 10) NOT NULL DEFAULT 0,
    net_pnl                  NUMERIC(20, 10) NOT NULL DEFAULT 0,
    fees                     NUMERIC(20, 10) NOT NULL DEFAULT 0,
    max_drawdown             NUMERIC(20, 10),
    turnover_notional        NUMERIC(30, 10),
    exposure_time_pct        DOUBLE PRECISION,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (trade_date, hypothesis_pk, symbol_id)
);

-- 10) Governance/audit event log
CREATE TABLE IF NOT EXISTS rc.audit_events (
    audit_event_id           BIGSERIAL PRIMARY KEY,
    ts                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_role               TEXT NOT NULL CHECK (actor_role IN ('coordinator', 'architect', 'executor', 'guardian', 'capital_committee', 'system')),
    actor_id                 TEXT,
    event_type               TEXT NOT NULL,
    target_type              TEXT,
    target_id                TEXT,
    artifact_uri             TEXT,
    payload                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_hash_sha256        TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_ts ON rc.audit_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_target ON rc.audit_events (target_type, target_id, ts DESC);

COMMIT;
