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

-- D-01: Backtest run summary table (Phase 3 Plan 01).
-- One row per BacktestEngine run. run_id is a soft FK to runs.run_id.
-- Plain INSERT only — run_id (uuid7) is unique per run; no upsert needed.
CREATE TABLE IF NOT EXISTS backtests (
    run_id               VARCHAR     NOT NULL,   -- soft FK to runs.run_id
    strategy_id          VARCHAR     NOT NULL,
    symbol               VARCHAR     NOT NULL,
    timeframe            VARCHAR     NOT NULL,
    from_ts              TIMESTAMPTZ NOT NULL,
    to_ts                TIMESTAMPTZ NOT NULL,
    param_hash           VARCHAR     NOT NULL,
    equity_curve_path    VARCHAR     NOT NULL,   -- relative path to equity Parquet (D-03)
    -- Scalar metrics (all nullable — failed runs may not produce metrics)
    total_return         DOUBLE,
    cagr                 DOUBLE,
    sharpe               DOUBLE,
    sortino              DOUBLE,
    calmar               DOUBLE,
    max_dd               DOUBLE,
    max_dd_duration_bars BIGINT,
    win_rate             DOUBLE,
    expectancy           DOUBLE,
    profit_factor        DOUBLE,
    trade_count          INTEGER,
    avg_hold_bars        DOUBLE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id)
);

-- D-02: Per-trade attribution table (Phase 3 Plan 01).
-- Full attribution chain: signal → fill → trade row. D-11 exit_reason four-value Literal.
-- stop_price and target_price are nullable — non-ORB strategies may not emit stop/target.
-- Plain INSERT only — trade_id (uuid7) is unique per trade; no upsert needed.
CREATE TABLE IF NOT EXISTS trades (
    trade_id         VARCHAR     NOT NULL,   -- uuid7
    run_id           VARCHAR     NOT NULL,   -- soft FK to runs.run_id
    signal_id        VARCHAR     NOT NULL,   -- FK to Signal.signal_id
    strategy_id      VARCHAR     NOT NULL,
    side             VARCHAR     NOT NULL,   -- 'long' | 'short'
    entry_price      DOUBLE      NOT NULL,
    exit_price       DOUBLE      NOT NULL,
    exit_reason      VARCHAR     NOT NULL,   -- 'target'|'stop'|'eod_flat'|'manual' (D-11)
    entry_ts_utc     TIMESTAMPTZ NOT NULL,
    exit_ts_utc      TIMESTAMPTZ NOT NULL,
    pnl              DOUBLE      NOT NULL,
    size             INTEGER     NOT NULL,
    slippage_ticks   INTEGER     NOT NULL,
    mae              DOUBLE      NOT NULL,
    mfe              DOUBLE      NOT NULL,
    stop_price       DOUBLE,                 -- nullable: ORB-sourced; NULL for non-ORB
    target_price     DOUBLE,                 -- nullable: ORB-sourced; NULL for non-ORB
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_id)
);

-- Phase 4: Optimization grid + walk-forward tables (D-13).
-- All three tables use IF NOT EXISTS for idempotent schema application.

CREATE TABLE IF NOT EXISTS opt_runs (
    run_id            VARCHAR     PRIMARY KEY,  -- uuid7 (time-sortable)
    strategy_id       VARCHAR     NOT NULL,
    adr_hash          VARCHAR     NOT NULL,     -- SHA256 of opt-*.md ADR file
    param_grid_hash   VARCHAR     NOT NULL,     -- SHA256 of optspace.yaml param values
    is_window_months  INTEGER     NOT NULL,     -- e.g., 6
    oos_window_months INTEGER     NOT NULL,     -- e.g., 1
    step_months       INTEGER     NOT NULL,     -- e.g., 1
    seed              INTEGER     NOT NULL,
    fold_count        INTEGER     NOT NULL DEFAULT 0,
    completed_combos  INTEGER     NOT NULL DEFAULT 0,
    total_combos      INTEGER     NOT NULL DEFAULT 0,
    status            VARCHAR     NOT NULL,     -- 'running'|'complete'|'failed'
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opt_results (
    result_id             VARCHAR     PRIMARY KEY,  -- uuid7
    run_id                VARCHAR     NOT NULL,     -- soft FK to opt_runs.run_id
    fold_idx              INTEGER     NOT NULL,
    param_hash            VARCHAR     NOT NULL,
    opening_range_minutes INTEGER     NOT NULL,
    atr_stop_mult         DOUBLE      NOT NULL,
    r_target              DOUBLE      NOT NULL,
    is_sharpe             DOUBLE,
    oos_sharpe            DOUBLE,
    is_return             DOUBLE,
    oos_return            DOUBLE,
    edge_ratio            DOUBLE,                   -- is_sharpe / oos_sharpe; NULL if oos_sharpe=0
    equity_curve_path     VARCHAR,
    git_sha               VARCHAR     NOT NULL,
    data_hash             VARCHAR     NOT NULL,
    seed                  INTEGER     NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS holdout_burns (
    burn_id    VARCHAR     PRIMARY KEY,   -- uuid7
    run_id     VARCHAR     NOT NULL,      -- soft FK to opt_runs.run_id
    burned_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    quarter    VARCHAR     NOT NULL       -- e.g., '2026Q2' (YYYYQ format)
);
