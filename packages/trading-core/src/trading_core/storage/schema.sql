-- packages/trading-core/src/trading_core/storage/schema.sql
-- Single source of truth for DDL. DuckDBStore reads this verbatim on init.
-- All timestamps are tz-aware UTC. Bar timestamps are OPEN time (MD-06 convention).

CREATE TABLE IF NOT EXISTS bars (
    symbol     VARCHAR     NOT NULL,
    timeframe  VARCHAR     NOT NULL,  -- '1m' | '5m' | '15m'
    ts_utc     TIMESTAMPTZ NOT NULL,  -- bar OPEN time, UTC (MD-06)
    open       DOUBLE      NOT NULL,
    high       DOUBLE      NOT NULL,
    low        DOUBLE      NOT NULL,
    close      DOUBLE      NOT NULL,
    volume     BIGINT      NOT NULL,
    rollover_seam BOOLEAN  NOT NULL DEFAULT FALSE,
    provider   VARCHAR     NOT NULL,  -- 'twelve_data' | 'tradingview_mcp'
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, ts_utc)
);

CREATE TABLE IF NOT EXISTS bar_gaps (
    symbol      VARCHAR     NOT NULL,
    timeframe   VARCHAR     NOT NULL,
    ts_utc      TIMESTAMPTZ NOT NULL,  -- bar OPEN time, UTC (MD-06)
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provider    VARCHAR     NOT NULL,
    run_id      VARCHAR,                 -- soft FK to runs.run_id
    PRIMARY KEY (symbol, timeframe, ts_utc)
);

CREATE TABLE IF NOT EXISTS instruments (
    symbol     VARCHAR PRIMARY KEY,
    payload    JSON NOT NULL,            -- serialized Instrument Pydantic model
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      VARCHAR PRIMARY KEY,     -- uuid7 (time-sortable)
    git_sha     VARCHAR     NOT NULL,
    data_hash   VARCHAR     NOT NULL,    -- sha256 of bar payload (see Reproducibility Hashing)
    param_hash  VARCHAR     NOT NULL,    -- sha256 of canonical JSON CLI args
    seed        INTEGER     NOT NULL,
    adr_hash    VARCHAR     NOT NULL,    -- sha256 of .planning/decisions/0001-data-provider.md
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      VARCHAR     NOT NULL,    -- 'ok' | 'failed' | 'partial'
    notes       VARCHAR     NOT NULL DEFAULT ''
);
