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
    status               VARCHAR     NOT NULL DEFAULT 'complete',  -- Phase 7: D-15 polling
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

-- Phase 5: Risk state append-only table (D-06/D-07).
-- One row per update; full audit trail of all three DD model states side-by-side.
CREATE TABLE IF NOT EXISTS risk_state (
    id                       VARCHAR        PRIMARY KEY,    -- uuid7
    ts_utc                   TIMESTAMPTZ    NOT NULL,
    date                     DATE           NOT NULL,        -- trading date (ET)
    session_id               VARCHAR        NOT NULL,        -- today's run_id (UUID7)
    equity_dollars           DECIMAL(20,10) NOT NULL,
    realized_pnl_dollars     DECIMAL(20,10) NOT NULL,
    open_exposure_dollars    DECIMAL(20,10) NOT NULL,
    hwm_static               DECIMAL(20,10) NOT NULL,
    floor_static             DECIMAL(20,10) NOT NULL,
    hwm_trailing_eod         DECIMAL(20,10) NOT NULL,
    floor_trailing_eod       DECIMAL(20,10) NOT NULL,
    hwm_trailing_intraday    DECIMAL(20,10) NOT NULL,
    floor_trailing_intraday  DECIMAL(20,10) NOT NULL
);

-- Phase 5: Audit log — every event persisted synchronously (SP-03 / D-09).
-- Append-only; no primary-key conflict possible (uuid7 is unique per event).
CREATE TABLE IF NOT EXISTS audit_log (
    event_id     VARCHAR        PRIMARY KEY,    -- uuid7 (time-sortable)
    ts_utc       TIMESTAMPTZ    NOT NULL,
    topic        VARCHAR        NOT NULL,        -- EventBus topic constant
    entity_id    VARCHAR        NOT NULL,        -- signal_id / fill_id / run_id
    reason_code  VARCHAR        NOT NULL,        -- 'dd_floor_violation', 'pass', 'kill_switch', etc.
    payload_json VARCHAR        NOT NULL         -- serialized Pydantic model (JSON)
);

-- Phase 5: Engine state — persisted on every state change (D-10/D-11).
-- Append-only; most-recent row = current state.
-- WR-02: kind column discriminates global engine state ('global') from
-- per-strategy enabled state ('strategy') so session_id namespace never collides.
CREATE TABLE IF NOT EXISTS engine_state (
    id         VARCHAR        PRIMARY KEY,    -- uuid7
    session_id VARCHAR        NOT NULL,
    ts_utc     TIMESTAMPTZ    NOT NULL,
    state      VARCHAR        NOT NULL,       -- 'running' | 'killed' | 'paused' | 'flatten_requested'
    kind       VARCHAR        NOT NULL DEFAULT 'global'  -- 'global' | 'strategy' (WR-02)
);

-- Phase 6: TV overlay registry (TV-02).
-- One row per shape drawn on the TV chart via draw_shape MCP tool.
-- shape_id is populated from the entity_id field in the draw_shape response.
-- deleted_at NULL = active; set by nightly cleanup task (Plan 04).
CREATE TABLE IF NOT EXISTS tv_overlays (
    overlay_id    VARCHAR     PRIMARY KEY,          -- uuid7 (time-sortable)
    strategy_id   VARCHAR     NOT NULL,
    signal_id     VARCHAR     NOT NULL,             -- soft FK to audit_log.entity_id
    shape_kind    VARCHAR     NOT NULL,             -- 'entry_arrow'|'stop_line'|'target_line'|'orb_box'
    shape_id      VARCHAR     NOT NULL,             -- entity_id from draw_shape MCP response
    trading_date  DATE        NOT NULL,             -- ET trading date the shape belongs to
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at    TIMESTAMPTZ                       -- NULL = active; set by nightly cleanup
);

-- Phase 6: TV alert registry (TV-07).
-- One row per alert created via alert_create MCP tool.
-- deleted_at NULL = active; set when strategy toggled off.
CREATE TABLE IF NOT EXISTS tv_alerts (
    alert_id      VARCHAR     PRIMARY KEY,          -- uuid7
    strategy_id   VARCHAR     NOT NULL,
    tv_alert_id   VARCHAR     NOT NULL,             -- alert ID returned by alert_create MCP tool
    condition     VARCHAR     NOT NULL,             -- free-form alert condition description
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at    TIMESTAMPTZ                       -- NULL = active; set on strategy toggle-off
);
