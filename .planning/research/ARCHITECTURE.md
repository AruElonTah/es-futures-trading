# Architecture Research

**Domain:** Single-operator intraday futures backtest + paper-trading system with Bloomberg-Terminal-style web UI and TradingView MCP integration
**Researched:** 2026-05-14
**Confidence:** HIGH (patterns drawn from NautilusTrader, Backtrader, AAT, OpenBB, PyEventBT, and the official MCP/uv/FastAPI docs; verified against current 2026 conventions)

---

## System Overview

The system is a **single-host, multi-process Python + Node + TypeScript application** with a single source-of-truth event bus inside the Python core. Three persistent processes plus on-demand workers:

1. **Trading Core (Python, async)** — owns market data, strategies, signals, risk, paper executor, persistence. Hosts the in-process asyncio event bus.
2. **API Gateway (FastAPI, same Python process as Core in v1)** — REST + WebSocket surface. Subscribes to the event bus and fans out to the UI.
3. **Web UI (Next.js, separate Node process)** — Bloomberg-style dense React frontend with Lightweight Charts.
4. **TradingView MCP sidecar (Node, spawned on demand)** — the existing `tradingview-mcp-jackson` server, launched as a stdio subprocess from a Python `MCPClient` wrapper.
5. **Optimization workers (Python, `ProcessPoolExecutor`)** — short-lived, CPU-bound. Spawned by Core when a grid/walk-forward run is requested.

```
                          BROWSER (localhost:3000)
                          ----------------------
                          Next.js UI (dark, dense)
                          - Chart panel (Lightweight Charts)
                          - Blotter / equity / trade history
                          - Strategy controls / heatmaps
                                    |
                                    | WebSocket (bars, signals, fills, equity)
                                    | + REST (history, backtests, optimization)
                                    v
+---------------------------------------------------------------------------+
|                  TRADING CORE PROCESS  (Python 3.11, asyncio)             |
|                                                                           |
|   +-----------+   +-------------+   +---------+   +------+   +---------+ |
|   | DataSource|-->| StrategyEng |-->| Signals |-->| Risk |-->| PaperExe| |
|   | (Twelve   |   | (ORB +      |   |  Bus    |   |Mgr  |   | cutor   | |
|   |  Data)    |   |  on_bar)    |   |(asyncio)|   |     |   |         | |
|   +-----------+   +-------------+   +----+----+   +---+--+   +----+----+ |
|         |                |               |             |          |      |
|         |                |               +-------------+----------+      |
|         |                |                             |                 |
|         v                v                             v                 |
|   +-----------------------------------------------------------+         |
|   |              EventBus  (asyncio pub/sub topics)           |         |
|   |   topics: bars.1m, signals, fills, positions, equity,      |         |
|   |           risk.events, opt.progress                        |         |
|   +-----------------------------------------------------------+         |
|         |                |                  |              |             |
|         v                v                  v              v             |
|   +-----------+   +-------------+   +-------------+  +-----------+      |
|   | DuckDB +  |   | FastAPI WS  |   | TV MCP      |  | Backtester|      |
|   | Parquet   |   | broadcaster |   | Bridge      |  | (VBT)     |      |
|   | (storage) |   | (push to UI)|   | (stdio MCP) |  | (on-demand)      |
|   +-----------+   +-------------+   +------+------+  +-----+-----+      |
|                                            |               |             |
|                                            |               | spawns      |
+--------------------------------------------|---------------|-------------+
                                             |               |
                                             v               v
                                    +----------------+  +---------------+
                                    | TradingView    |  | Optimization  |
                                    | MCP server     |  | workers       |
                                    | (Node, stdio)  |  | (ProcessPool) |
                                    | tradingview-   |  | grid + WFA    |
                                    | mcp-jackson    |  +---------------+
                                    +-------+--------+
                                            |
                                            | CDP
                                            v
                                    TradingView Desktop
```

**Key architectural choices, with rationale:**

- **Single Python process for Core + API in v1** — Backtrader, AAT, PyEventBT all prove this works fine for single-operator low-frequency systems. Splitting into microservices is premature complexity and breaks the "same code in backtest and live" property.
- **Asyncio event bus (no Redis, no Kafka)** — single operator, in-process consumers only. Redis pub/sub would buy nothing and double the ops surface. (Verified against [permitio/fastapi_websocket_pubsub](https://github.com/permitio/fastapi_websocket_pubsub) which only recommends Redis for multi-worker scale-out.)
- **Optimization runs in `ProcessPoolExecutor`, not threads** — VectorBT is NumPy/Numba heavy and the GIL would serialize it. Keep the core process responsive while a 10k-config sweep runs.
- **TV MCP is a sidecar, not a peer** — Python core is the brain; TV MCP is a write-mostly drawing surface plus an optional replay data source. This matches PROJECT.md's "Python is the brain, TradingView is the chart and validation surface."
- **Same strategy code in backtest and live** — non-negotiable. Backtester and live engine both feed `Strategy.on_bar(bar)` and consume `Signal`. Only the data source and executor swap.

---

## Component Boundaries

The codebase divides into the six modules called out in PROJECT.md plus three infrastructure layers. Every module exposes a small `Protocol`-typed public interface; implementations live behind those interfaces so test doubles and provider swaps are mechanical.

| Module | Owns | Public Interface | Persists To | Broadcasts |
|--------|------|------------------|-------------|------------|
| **MarketData** | Bar ingestion, RTH filtering, gap detection, continuous-contract assembly | `DataSource.get_bars(symbol, tf, start, end) -> DataFrame`, `DataSource.stream_bars(symbol, tf) -> AsyncIterator[Bar]` | DuckDB `bars` table + Parquet partitions | `bars.{tf}` topic |
| **StrategyEngine** | Indicator computation, `on_bar` dispatch, ORB/future strategies, signal construction | `Strategy.on_bar(bar) -> Signal \| None`, `Strategy.params: BaseModel`, `IndicatorRegistry` | (none — pure compute) | `signals` topic |
| **Backtester** | Vectorized historical run, fill simulation (slippage/commission), trade ledger, metrics | `Backtester.run(strategy, bars, risk_cfg) -> BacktestResult` | DuckDB `backtests`, `trades`, `equity` | `backtest.progress`, `backtest.complete` |
| **Optimization** | Grid expansion, walk-forward folds, scheduler, leaderboard | `Optimizer.run(strategy_cls, param_space, bars, mode) -> OptRun`, `Optimizer.heatmap(run_id, x, y) -> array` | DuckDB `opt_runs`, `opt_results` | `opt.progress`, `opt.complete` |
| **SignalPipeline** | The asyncio event bus itself; routes `Signal` → risk → executor; audit log | `EventBus.publish(topic, msg)`, `EventBus.subscribe(topic) -> AsyncIterator`, `Pipeline.start()` | DuckDB `audit_log` + CSV mirror | (it IS the broadcaster) |
| **RiskManager** | Pre-trade checks, ATR sizing, daily-DD circuit breaker, equity HWM | `RiskManager.evaluate(signal, account_state) -> RiskedOrder \| RejectReason` | DuckDB `risk_decisions`, `account_state` | `risk.events`, `equity` |
| **PaperExecutor** | Next-bar fill against live or replayed bars, position tracking, P&L | `Executor.submit(order) -> Fill`, `Executor.positions() -> dict` | DuckDB `fills`, `positions` | `fills`, `positions` |
| **APIGateway** | REST endpoints, WS broadcaster, auth-free localhost-bound | FastAPI routers + `/ws` endpoint | (none — read-through) | (forwards bus to WS clients) |
| **TVBridge** | Spawns + supervises the MCP sidecar; exposes typed Python wrappers around `draw_shape`, `alert_create`, `replay_*`, `data_get_ohlcv` | `TVBridge.draw_orb_box(...)`, `TVBridge.draw_signal(...)`, `TVBridge.start_replay(...)`, `TVBridge.fetch_replay_bars(...)` | (none — outbound only) | subscribes to `signals`, `fills` for auto-drawing |
| **Storage** | DuckDB connection pool, Parquet writer, schema migrations | `Repo.bars`, `Repo.trades`, `Repo.opt`, … (one repo per table family) | DuckDB file + Parquet dir | (none) |

### Interface Contracts (Python `Protocol` style)

```python
# market_data/protocols.py
class DataSource(Protocol):
    async def get_bars(self, symbol: str, tf: Timeframe,
                       start: datetime, end: datetime) -> pl.DataFrame: ...
    async def stream_bars(self, symbol: str, tf: Timeframe) -> AsyncIterator[Bar]: ...

# strategy/protocols.py
class Strategy(Protocol):
    params: BaseModel
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None: ...
    def on_session_start(self, session: SessionContext) -> None: ...

# risk/protocols.py
class RiskManager(Protocol):
    def evaluate(self, signal: Signal, state: AccountState) -> RiskedOrder | Reject: ...

# execution/protocols.py
class Executor(Protocol):
    async def submit(self, order: RiskedOrder) -> Fill: ...
```

**These four `Protocol`s are the load-bearing seams.** Every other module is implementation. A future IB-live executor or Polygon data source is just a new class that satisfies one of these — no other code changes.

---

## Data Flow

### Live / paper-trading flow (also the backtest flow with identical code)

```
[Twelve Data REST]
   |
   | hourly poll for new bars
   v
+-----------------+
| TwelveDataSource|   (writes:  DuckDB bars table + Parquet partition)
+-----------------+   (publishes: bars.1m topic)
   |
   v   subscribe("bars.1m")
+-----------------+
| StrategyEngine  |   ORB strategy reads bar, returns Signal | None
+-----------------+   (publishes: signals topic)
   |
   v   subscribe("signals")
+-----------------+
| RiskManager     |   ATR-sized contracts, daily-DD check
+-----------------+   (writes: risk_decisions)  (publishes: risk.events)
   |   RiskedOrder or Reject
   v
+-----------------+
| PaperExecutor   |   Fills against next bar with slippage
+-----------------+   (writes: fills, positions)  (publishes: fills, positions)
   |
   v   subscribe("fills")
+-----------------+      +-----------------+
| EquityTracker   |----->| TVBridge        |--> draw_shape on TV chart
+-----------------+      +-----------------+
   |
   v  (publishes: equity)
+-----------------+
| FastAPI WS hub  |  fans out bars, signals, fills, positions, equity to UI
+-----------------+
```

### Backtest flow (offline, batch)

```
User clicks "Run Backtest" in UI
   |
   v  POST /api/backtests   (params + date range)
+-----------------+
| FastAPI handler |
+-----------------+
   |
   v
+-----------------+
| Backtester      |  loads bars from DuckDB, instantiates Strategy with
| (VectorBT)      |  params, runs vectorized; OR for path-dependent logic
+-----------------+  drives the SAME on_bar pipeline through a SyntheticClock
   |
   v
DuckDB: backtests row, trades, equity per timestamp
   |
   | bus.publish("backtest.complete", run_id)
   v
FastAPI WS  --->  UI refreshes equity / trade list
```

### Optimization flow

```
User submits param grid (UI form -> POST /api/optimizations)
   |
   v
+-----------------+
| Optimizer       |  expands grid, builds N (strategy_cfg, fold) tasks
+-----------------+
   |
   | submit to ProcessPoolExecutor (max_workers = cpu_count - 1)
   v
+-----------------+   x N workers
| Worker          |   loads bars (read-only DuckDB), runs Backtester,
| (subprocess)    |   returns metrics dict
+-----------------+
   |
   | each completion: bus.publish("opt.progress", {done, total, best_so_far})
   v
DuckDB: opt_runs, opt_results
   |
   v
WS broadcaster -> UI progress bar + live leaderboard
```

### Write/read responsibilities — explicit

| Artifact | Sole Writer | Readers |
|----------|-------------|---------|
| `bars` (DuckDB + Parquet) | MarketData | StrategyEngine, Backtester, Optimizer workers, API (history endpoint) |
| `signals` (audit only) | SignalPipeline middleware | API (history), TVBridge (auto-draw) |
| `fills`, `positions` | PaperExecutor | RiskManager, EquityTracker, API |
| `risk_decisions` | RiskManager | API (forensic view) |
| `trades`, `equity` (backtest) | Backtester | Optimizer (objective fn), API |
| `opt_runs`, `opt_results` | Optimizer | API (heatmaps, leaderboard) |
| `audit_log` | SignalPipeline | API (forensic replay) |

**One writer per table.** Multiple readers fine. This is the single biggest correctness lever — see PITFALLS.md for the rewrite stories it prevents.

---

## Runtime Model

### Processes at steady state

| Process | When running | Why a separate process |
|---------|--------------|------------------------|
| `trading-core` (Python) | Always (hosts Core + FastAPI on `uvicorn`) | The brain. Asyncio event loop dispatches bars → strategy → risk → executor and serves WS/REST. |
| `web` (Node, Next.js dev or `next start`) | Always while UI is open | Frontend dev server (or built static + node server). |
| `tradingview-mcp` (Node, stdio child) | Spawned by `trading-core` on first TV call, supervised, restarted on crash | The MCP server uses stdio; it's a subprocess of the Core, not a peer service. Supervisor in Core keeps it alive. |
| `opt-worker-*` (Python subprocess) | Only during an optimization run | CPU-bound NumPy/Numba; GIL prevents in-process parallelism. `ProcessPoolExecutor` with N-1 workers. |
| TradingView Desktop | Always (user's existing app) | External. Connected to via CDP by the MCP sidecar. |

### Concurrency model inside `trading-core`

Single asyncio event loop. All bus consumers are `async def` coroutines awaiting `bus.subscribe(topic)`. Components that block (DuckDB writes, file I/O, MCP calls) wrap blocking calls in `asyncio.to_thread()` so the loop stays responsive.

```python
# main.py — simplified
async def main():
    bus = EventBus()
    repo = Repo(duckdb_path="data/trading.duckdb")
    data_source = TwelveDataSource(api_key=settings.twelve_data_key, repo=repo)
    tv = TVBridge.spawn()           # starts MCP subprocess via stdio
    strategy = ORBStrategy(params=settings.orb)
    risk = RiskManager(cfg=settings.risk)
    executor = PaperExecutor(repo=repo)
    pipeline = SignalPipeline(bus, risk, executor, repo)

    app = build_fastapi(bus, repo)  # REST + WS
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000))

    await asyncio.gather(
        data_source.run(bus),       # poll Twelve Data, publish bars
        strategy.run(bus),          # subscribe bars, publish signals
        pipeline.run(),             # subscribe signals, risk-check, execute
        tv.run(bus),                # subscribe signals/fills, draw on TV
        server.serve(),             # FastAPI + WS
    )
```

### Why not split FastAPI into its own process for v1?

- Single operator on localhost. No multi-tenant concerns.
- The event bus is in-process — splitting forces a network hop (Redis or ZMQ) for every UI update.
- Backtrader, AAT, PyEventBT all run this way. NautilusTrader splits engines from adapters but stays in one process at this scale.
- Migration path is trivial later: the `EventBus` interface is the seam. Swap the in-process impl for a Redis-backed one and the API can move to a second process with no other code changes.

---

## Repository Layout

**Decision: single monorepo, NOT Turborepo.** Two-tree polyrepo would force version coordination on every change. Turborepo adds Node-world complexity to a project that is 80% Python. Use **uv workspaces** for Python and a simple `apps/web/` for Next.js — Turborepo's caching/orchestration buys nothing for a single-developer Python-dominant repo.

```
Day Trading/
├── pyproject.toml              # uv workspace root
├── uv.lock
├── .python-version              # 3.11
├── .env                         # secrets (gitignored): TWELVE_DATA_API_KEY, ...
├── .env.example
├── config/
│   ├── system.yaml              # data paths, ports, log levels
│   ├── risk.yaml                # account size, max risk %, DD limit
│   ├── strategies/
│   │   ├── orb.yaml             # opening-range minutes, ATR mult, R target
│   │   └── orb.optspace.yaml    # grid for optimization runs
│   └── tradingview.yaml         # MCP command, default symbol, drawing colors
├── data/
│   ├── trading.duckdb           # gitignored
│   └── parquet/
│       ├── bars/
│       │   ├── symbol=ES1!/tf=1m/year=2025/month=01/part-000.parquet
│       │   └── ...
│       └── audit/
│           └── date=2026-05-14/audit.parquet
├── packages/                    # Python workspace members
│   ├── trading-core/
│   │   ├── pyproject.toml
│   │   └── src/trading_core/
│   │       ├── __init__.py
│   │       ├── main.py          # async entry point (uvicorn + bus)
│   │       ├── config.py        # Pydantic Settings root
│   │       ├── bus.py           # EventBus implementation
│   │       ├── market_data/
│   │       │   ├── protocols.py
│   │       │   ├── twelve_data.py
│   │       │   ├── rth_filter.py
│   │       │   └── continuous_contract.py
│   │       ├── strategy/
│   │       │   ├── base.py      # Strategy Protocol + StrategyContext
│   │       │   ├── orb.py       # Opening Range Breakout
│   │       │   └── indicators/  # ATR, VWAP, EMA, ADR
│   │       ├── backtest/
│   │       │   ├── engine.py    # VectorBT-backed
│   │       │   ├── fills.py     # slippage + commission model
│   │       │   └── metrics.py
│   │       ├── optimization/
│   │       │   ├── grid.py
│   │       │   ├── walk_forward.py
│   │       │   └── worker.py    # subprocess entrypoint
│   │       ├── pipeline/
│   │       │   ├── pipeline.py  # signals -> risk -> executor wiring
│   │       │   └── audit.py
│   │       ├── risk/
│   │       │   ├── manager.py
│   │       │   ├── sizing.py    # ATR -> contracts (MES conversion)
│   │       │   └── circuit.py   # daily DD breaker
│   │       ├── execution/
│   │       │   ├── paper.py
│   │       │   └── ledger.py
│   │       └── storage/
│   │           ├── repo.py      # DuckDB connection mgr
│   │           ├── parquet.py
│   │           └── migrations/
│   │               └── 001_initial.sql
│   ├── api/
│   │   ├── pyproject.toml
│   │   └── src/api/
│   │       ├── __init__.py
│   │       ├── app.py           # FastAPI app factory
│   │       ├── routers/
│   │       │   ├── bars.py
│   │       │   ├── strategies.py
│   │       │   ├── backtests.py
│   │       │   ├── optimization.py
│   │       │   ├── positions.py
│   │       │   └── tv.py        # POST /tv/draw, /tv/replay, etc.
│   │       └── ws/
│   │           ├── manager.py   # ConnectionManager
│   │           └── broadcaster.py  # bus -> WS pump
│   └── tv-bridge/
│       ├── pyproject.toml
│       └── src/tv_bridge/
│           ├── __init__.py
│           ├── client.py        # async stdio MCP client wrapper
│           ├── supervisor.py    # spawn, restart, health
│           ├── drawings.py      # high-level draw_orb_box(), draw_signal()
│           ├── replay.py        # high-level replay session helpers
│           └── alerts.py
├── apps/
│   └── web/                     # Next.js 15 frontend
│       ├── package.json
│       ├── next.config.js
│       ├── tsconfig.json
│       ├── tailwind.config.ts
│       ├── public/
│       └── src/
│           ├── app/
│           │   ├── layout.tsx
│           │   └── page.tsx     # main dashboard
│           ├── components/
│           │   ├── chart/       # Lightweight Charts wrappers
│           │   ├── blotter/
│           │   ├── equity/
│           │   ├── trades/
│           │   └── controls/
│           ├── lib/
│           │   ├── api.ts       # REST client (OpenAPI-typed)
│           │   ├── ws.ts        # WS client with reconnect
│           │   └── types.ts     # generated from FastAPI OpenAPI
│           └── styles/
├── scripts/
│   ├── dev.ps1                  # one-shot: launch core + web
│   ├── seed_bars.py             # backfill historical ES bars
│   └── migrate.py               # DuckDB schema migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│       └── bars_es_2025-01.parquet  # known-good test data
├── .planning/                   # GSD planning artifacts (this folder)
└── README.md
```

**Why this layout works:**

- **uv workspace** (`[tool.uv.workspace] members = ["packages/*"]` at root) gives one `.venv`, one `uv.lock`, but separate `pyproject.toml` per package so the strategy code can be imported by both the live API and standalone backtest scripts without circular dependencies.
- **`src/` layout per package** is the [PyPA-recommended 2026 default](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) — tests run against the *installed* package, catching import-path bugs early.
- **`apps/web/` not `packages/web/`** — Python and Node ecosystems don't mix in one workspace; keep them as siblings under the same git root.
- **`config/` at the root, not inside `trading-core`** — the same YAML is loaded by both the live process and the optimization workers. Sharing it via a package would force imports.
- **`data/` is gitignored** — Parquet partitioned by `symbol/tf/year/month` is what DuckDB needs for partition pruning ([source](https://medium.com/@bhagyarana80/5-duckdb-partitioning-moves-for-faster-time-series-reads-00c656b4fcfb)).
- **`tv-bridge/` is its own package**, not a submodule of `trading-core`, because (a) it's the only package that depends on the MCP SDK and (b) it could be replaced wholesale by a Pine-only bridge or a different chart later.

---

## Configuration

**Decision: YAML for declarative config + Pydantic Settings for loading + `.env` for secrets only.** This is the pattern documented in [pydantic-settings-yaml](https://pypi.org/project/pydantic-settings-yaml/) and recommended in the linked best-practices write-ups.

### Three tiers

| Tier | Format | Lives In | Reloadable | Examples |
|------|--------|----------|------------|----------|
| **Secrets** | `.env` (gitignored) | repo root | No (restart) | `TWELVE_DATA_API_KEY`, MCP CDP debug port |
| **System** | YAML | `config/system.yaml`, `config/risk.yaml` | No (restart) | DuckDB path, FastAPI port, log level, account size, DD limit, MES tick value |
| **Strategy params** | YAML | `config/strategies/<name>.yaml` | YES (hot-reload via UI) | ORB minutes, ATR mult, R target, session window |

### Loader

```python
# trading_core/config.py
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="")
    twelve_data_api_key: str
    tv_cdp_port: int = 9222

class RiskCfg(BaseModel):
    account_usd: float = 50_000
    max_risk_pct: float = 0.02
    daily_dd_usd: float = 2_000
    instrument: str = "MES"     # sizing target
    tick_value_usd: float = 1.25

class ORBParams(BaseModel):
    opening_minutes: int = 15
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    r_target: float = 2.0

class Settings(BaseModel):
    secrets: Secrets
    risk: RiskCfg
    orb: ORBParams
    duckdb_path: str
    parquet_dir: str
    fastapi_port: int = 8000

def load() -> Settings:
    risk = RiskCfg(**yaml.safe_load(open("config/risk.yaml")))
    orb = ORBParams(**yaml.safe_load(open("config/strategies/orb.yaml")))
    system = yaml.safe_load(open("config/system.yaml"))
    return Settings(
        secrets=Secrets(),    # auto-loads from env / .env
        risk=risk, orb=orb,
        **system,
    )
```

**Why this split:**
- Secrets in `.env` because they're per-machine and must never be committed.
- System config in YAML because it's tree-structured (better than `.env` for nested risk/data settings) and changes per-environment, not per-strategy.
- Strategy params in their own YAML because they're the thing the user edits most — and they're the thing the UI can write to directly (with Pydantic validation on the way in) for hot-reload. The Optimizer reads `orb.optspace.yaml` for grid bounds rather than hard-coding them.

---

## TradingView MCP Integration

**Pattern: long-lived stdio subprocess managed by a supervisor, exposed to the rest of Core via a thin async wrapper.** This is concrete and load-bearing, not aspirational.

### How Python talks to MCP

The TV MCP server (`tradingview-mcp-jackson`) is a Node.js MCP server at `C:\Users\Admin\tradingview-mcp-jackson\src\server.js` that communicates over stdio with JSON-RPC 2.0 framing. The official `mcp` Python SDK provides `stdio_client` + `ClientSession` which spawns it as a subprocess and keeps the connection persistent for the lifetime of the client — this is the documented pattern for stdio MCP transports ([modelcontextprotocol.io/quickstart/client](https://modelcontextprotocol.io/quickstart/client)).

```python
# tv_bridge/client.py
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class TVMCPClient:
    def __init__(self, server_js_path: str):
        self._params = StdioServerParameters(
            command="node",
            args=[server_js_path],
            env=None,   # inherits parent env (TV CDP port, etc.)
        )
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self):
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(self._params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    async def call(self, tool: str, **args) -> Any:
        result = await self._session.call_tool(tool, args)
        return result.content
```

### Supervisor

The MCP subprocess can die (e.g. user closed TV Desktop, CDP disconnected). Don't crash the Core — restart it.

```python
# tv_bridge/supervisor.py
class TVBridge:
    def __init__(self, server_js: str, bus: EventBus):
        self.server_js = server_js
        self.bus = bus
        self.client: TVMCPClient | None = None

    async def run(self):
        # auto-draw signals as they fire
        async for signal in self.bus.subscribe("signals"):
            try:
                await self._ensure_client()
                await self.draw_signal(signal)
            except MCPConnectionError:
                await self._restart()

    async def _ensure_client(self):
        if self.client is None:
            self.client = await TVMCPClient(self.server_js).__aenter__()

    async def _restart(self):
        if self.client:
            await self.client.__aexit__(None, None, None)
        self.client = None
        await asyncio.sleep(1)  # backoff
```

### High-level operations (what the rest of the system sees)

```python
class TVBridge:
    async def draw_orb_box(self, date: date, high: float, low: float) -> str:
        return await self.client.call("draw_shape", shape="rectangle", ...)

    async def draw_signal(self, signal: Signal) -> None:
        # entry arrow + stop line + target line, all in one call group
        ...

    async def start_replay(self, symbol: str, start: datetime) -> ReplaySession:
        return await self.client.call("replay_start", symbol=symbol, ...)

    async def fetch_replay_bars(self, n: int) -> list[Bar]:
        # alternative DataSource impl backed by replay
        return await self.client.call("data_get_ohlcv", count=n)
```

### Three roles TV plays in this system

1. **Output surface (always-on)** — every signal and fill is drawn on the live TV chart via `draw_shape`. Subscribes to `signals` and `fills` topics on the bus.
2. **Alternative data source (opt-in)** — `TVReplayDataSource` implements the `DataSource` protocol, fetching bars from a TV replay session. Useful to validate that Twelve Data bars match the bars the user is eyeballing. Selected per-run, not per-process.
3. **Alert authoring (manual)** — UI button "Create alert at $X" → `alert_create` via MCP. Not used in automated trading; supplementary signal source for the human.

### Failure isolation

- If TV is closed or CDP is unreachable, **trading does not stop**. The bus consumer in `TVBridge.run()` catches MCP errors and logs them; the strategy/risk/executor pipeline runs independently and persists everything to DuckDB. When TV comes back, drawing resumes. This is critical — the chart is decoration, not a dependency for trading logic.

---

## Suggested Build Order

The vertical-MVP slice — minimum end-to-end demonstrably-useful system — is:

> **Pull one day of 1m ES bars → run ORB strategy on them → emit one signal → paper-fill it → see candles + that one signal + that one fill on the Next.js chart.**

Everything else is depth on top of this skeleton. Phases below are stacked so each one closes a feedback loop the previous one couldn't.

### Phase 1: Foundation (the dirt under everything)
- Scaffold the uv workspace + Next.js app (`packages/trading-core`, `packages/api`, `apps/web`).
- `EventBus` (asyncio pub/sub, in-process). 50 lines.
- Pydantic Settings + `config/*.yaml` loader.
- DuckDB `Repo` skeleton + initial migration.

**Unblocks:** every other phase.

### Phase 2: Data In (the input edge)
- `DataSource` protocol + `TwelveDataSource` implementation (REST, 1m bars only initially).
- RTH filter, continuous-contract assembly.
- Parquet partitioning + DuckDB upsert path with idempotency.
- One CLI script: `seed_bars.py --symbol ES1! --from 2025-01-01 --to 2025-01-31`.

**Unblocks:** all backtest/strategy work. After this, you can `SELECT * FROM bars` and have real ES data.

### Phase 3: First Signal End-to-End (the vertical slice)
- `Strategy` protocol + `ORBStrategy` with hard-coded params.
- `SignalPipeline` plumbing (bars → strategy → bus).
- Minimal `RiskManager` (passes everything through, just sizes 1 MES contract).
- Minimal `PaperExecutor` (next-bar fill, no slippage yet).
- FastAPI `/bars` REST endpoint + `/ws` WebSocket.
- Next.js chart panel — Lightweight Charts loads historical bars + draws live markers from WS.

**Unblocks:** the visible feedback loop. After this, you can see ORB working on real data.

### Phase 4: Backtest Engine
- VectorBT integration in `backtest/engine.py`.
- Fill simulation with slippage (ticks) + commission (round-turn).
- Trade ledger persistence with full attribution (signal → fill → exit).
- Metrics: Sharpe, Sortino, max DD, win rate, expectancy, profit factor.
- UI: "Run Backtest" panel + equity curve + trade table.

**Unblocks:** strategy iteration. Until this exists, you can't tell if ORB is any good.

### Phase 5: Risk Manager + Audit
- Full ATR-based sizing (MES contracts from `risk.yaml`).
- Daily DD circuit breaker + per-strategy concurrency cap.
- Audit log table + CSV mirror — every signal, every decision, every fill, with reason codes.
- UI: blotter panel with open positions + distance-to-stop, daily-DD bar.

**Unblocks:** trusting the numbers. Audit log is what makes "reproducible, leakage-free results" verifiable.

### Phase 6: TradingView MCP Bridge
- `TVBridge` supervisor + stdio MCP client.
- Auto-draw ORB box on session open, signal arrows on fire, stop/target lines on fill.
- Failure isolation: MCP down ≠ trading halts.
- UI button: "Sync chart to selected date" (REST `/tv/focus`).

**Unblocks:** the daily workflow described in PROJECT.md ("when system focuses a date, push state to TV").

### Phase 7: Optimization
- Grid expansion (`opt.grid` from `orb.optspace.yaml`).
- `ProcessPoolExecutor` worker harness.
- Walk-forward analysis with configurable IS/OOS split.
- Persistence to `opt_runs` / `opt_results`.
- UI: heatmap (2-param slice) + OOS-ranked leaderboard.

**Unblocks:** the research loop. Until this, ORB params are guesses.

### Phase 8: TradingView Replay as Data Source
- `TVReplayDataSource` implementing the `DataSource` protocol.
- Per-backtest data-source selection.
- Cross-validation tool: run same backtest on Twelve Data bars vs TV replay bars, diff results.

**Unblocks:** the "validate against the same data the user is eyeballing" goal.

### Phase 9: Polish + Bloomberg-Density UI
- Multi-pane configurable grid (drag/resize panels).
- Dense monospace styling pass.
- Strategy hot-reload (edit YAML → UI button → live re-parameterize without restart).
- Daily/cumulative stats panel.

### Dependency graph

```
Phase 1 (Foundation)
   |
   v
Phase 2 (Data) -----+
   |                |
   v                |
Phase 3 (E2E slice) | <-- the vertical MVP — every later phase
   |                |     adds depth without changing this shape
   +----+----+------+
        |    |      |
        v    v      v
   Phase 4  Phase 5 Phase 6
   (Bt)    (Risk)  (TV draw)
        |    |
        +----+
        v
   Phase 7 (Optimization, depends on Backtest + Risk)
        |
        v
   Phase 8 (TV replay data source, depends on TV bridge + DataSource protocol)
        |
        v
   Phase 9 (Polish)
```

**Phase 3 is the load-bearing milestone** — once you can show a chart with a real signal and a real paper fill, you have proof the architecture works end-to-end. Every subsequent phase is incremental depth. If something is going to be wrong with the architecture, Phase 3 surfaces it.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Different code paths for backtest vs live
**What people do:** Build a "backtest mode" that has its own loop, its own signal handling, its own fill logic, and a separate "live mode" that re-implements all of it.
**Why it's wrong:** Guarantees backtest results will not match live results. Every divergence becomes a forensic investigation.
**Do this instead:** One `Strategy.on_bar()` API. Backtest drives it from a `SyntheticClock` over historical bars; live drives it from real bars. Same signal, same risk, same executor (paper for v1; broker adapter later).

### Anti-Pattern 2: Letting multiple components write the same table
**What people do:** Both the strategy module and the API mutate the `positions` row.
**Why it's wrong:** Race conditions, audit-log gaps, inconsistent state across reads.
**Do this instead:** Single writer per table. Every other component reads or sends a message to the writer.

### Anti-Pattern 3: Synchronous DuckDB writes on the event loop
**What people do:** `repo.insert_bar(bar)` directly inside the asyncio handler.
**Why it's wrong:** DuckDB inserts are blocking; the event loop stalls and bars back up.
**Do this instead:** `await asyncio.to_thread(repo.insert_bar, bar)` OR batch writes in a background task that drains a `asyncio.Queue`.

### Anti-Pattern 4: TV MCP as a hard dependency for trading
**What people do:** Block the signal pipeline on `await tv.draw_shape(...)` so that a TV disconnection halts trading.
**Why it's wrong:** Chart is decoration. A dead Chrome connection should not stop a strategy from generating signals.
**Do this instead:** TVBridge is a *subscriber* on the bus, not a step in the pipeline. Its failures are logged, not propagated.

### Anti-Pattern 5: One giant `pyproject.toml` for everything
**What people do:** Single root `pyproject.toml` with all dependencies (vectorbt + fastapi + mcp + everything).
**Why it's wrong:** Optimization workers import vectorbt + duckdb but not fastapi/mcp; spawning workers loads megabytes of unused code into every subprocess.
**Do this instead:** uv workspace with `trading-core`, `api`, `tv-bridge` as separate members. Workers only import `trading-core`.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Twelve Data REST | `httpx.AsyncClient` from `TwelveDataSource`. Hourly poll for new bars; on-demand for backfill. | Free tier rate limits. Cache aggressively in DuckDB. |
| TradingView (via MCP) | stdio subprocess managed by `TVBridge` supervisor. Persistent `ClientSession`. | Requires TV Desktop running with CDP enabled. Bridge auto-restarts on disconnect. |
| TradingView (replay) | Same MCP transport, different tool calls (`replay_start`, `data_get_ohlcv`). | Wrapped behind the `DataSource` protocol — backtest doesn't know if bars came from TV or Twelve Data. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| MarketData → StrategyEngine | EventBus topic `bars.{tf}` | Strategy never imports a DataSource. |
| StrategyEngine → RiskManager | EventBus topic `signals` | Risk doesn't know which strategy emitted; uses `signal.strategy_id`. |
| RiskManager → PaperExecutor | Direct call inside `SignalPipeline.run()` | Synchronous; risk check + submit happen atomically. |
| Core → API | EventBus subscription | API's WS broadcaster is just another bus consumer. |
| Core → TVBridge | EventBus subscription | TV draws are async fire-and-forget; failures logged. |
| Core → Opt Workers | `ProcessPoolExecutor.submit()` + result futures + bus events for progress | Workers can't touch the bus directly — they return metrics; the parent publishes progress events. |

---

## Sources

- [NautilusTrader Architecture (ports & adapters, MessageBus, single-threaded core)](https://nautilustrader.io/docs/latest/concepts/architecture/) — HIGH
- [Backtrader Cerebro engine, same code backtest/live](https://www.backtrader.com/docu/quickstart/quickstart/) — HIGH
- [AAT — Asynchronous Algorithmic Trading framework patterns](https://github.com/AsyncAlgoTrading/aat) — HIGH
- [OpenBB Platform architecture overview](https://openbb.co/blog/exploring-the-architecture-behind-the-openbb-platform) — HIGH
- [PyEventBT event-driven backtest/live unified loop](https://pyeventbt.com/getting-started/about-pyeventbt/) — MEDIUM
- [QuantStart — Event-Driven Backtesting (Signal/Order/Fill event hierarchy)](https://www.quantstart.com/articles/Event-Driven-Backtesting-with-Python-Part-I/) — HIGH
- [PyPA — src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) — HIGH
- [uv Workspaces documentation](https://docs.astral.sh/uv/concepts/projects/workspaces/) — HIGH
- [MCP Python SDK + stdio_client client quickstart](https://modelcontextprotocol.io/quickstart/client) — HIGH
- [MCP Transports spec (stdio persistence semantics)](https://modelcontextprotocol.info/docs/concepts/transports/) — HIGH
- [pydantic-settings YAML loading pattern](https://pypi.org/project/pydantic-settings-yaml/) — HIGH
- [FastAPI WebSocket pub/sub patterns for live dashboards](https://medium.com/@connect.hashblock/10-fastapi-websocket-patterns-for-live-dashboards-3e36f3080510) — MEDIUM
- [DuckDB partitioning for time-series Parquet reads](https://medium.com/@bhagyarana80/5-duckdb-partitioning-moves-for-faster-time-series-reads-00c656b4fcfb) — MEDIUM
- [next-fast-turbo reference (Next.js + FastAPI monorepo)](https://github.com/cording12/next-fast-turbo) — MEDIUM
- [tradingview-mcp-jackson README (local CDP-based stdio MCP server)](https://github.com/LewisWJackson/tradingview-mcp-jackson) — HIGH (verified by reading the local checkout)

---
*Architecture research for: single-operator intraday ES futures backtest + paper-trading system with TradingView MCP*
*Researched: 2026-05-14*
