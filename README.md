# GoldBot

Algorithmic **XAUUSD (gold) paper-trading system**: a candle-replay trading
engine with an independent risk engine, a trend-pullback strategy, a
simulated paper broker, a FastAPI backend (REST + WebSocket), and a React
operator dashboard. v1 intentionally ships paper mode only — no live broker
adapter exists, so "live" configuration can never place real orders.

> **Status:** functional and tested. Backend, risk pipeline, broker, DB
> mirroring, dashboard and CLI all validated end to end (see
> `docs/TEST_PLAN.md` and `docs/PROGRESS.md`).

---

## Architecture

```
src/goldbot/
├── core/          config (pydantic), domain models, exceptions, clock, logging
├── market_data/   CSV provider, normalizer, validators (UTC normalization)
├── indicators/    EMA, RSI, ATR, ADX
├── strategies/    trend_pullback (multi-timeframe, candle-close only)
├── risk/          RiskEngine (independent gate), risk limits, kill switch,
│                  position sizing
├── execution/     PaperBroker (spread/slippage/SL/TP simulation + JSON ledger)
├── database/      SQLAlchemy ORM models, Alembic migrations, optional mirror
├── api/           FastAPI app: REST /api/v1/*, WebSocket /ws, static SPA host
└── engine.py      TradingEngine: replay loop, proposals, approval lifecycle

frontend/          React + Vite dashboard (8 pages), served by the backend
                   when frontend/dist exists (single-port deployment) or via
                   the Vite dev server with API/WS proxying.
migrations/        Alembic environment + initial schema revision.
config/            settings.yaml (validated by pydantic-settings).
```

### Data flow

1. `CsvMarketDataProvider` loads historical 15m candles (validated, UTC).
2. `TradingEngine` replays them bar-by-bar (configurable speed, wraps at the
   end). Each bar walks price low → high → close through the broker so SL/TP
   trigger **intrabar**.
3. Indicators are recomputed on revealed bars; `TrendPullbackStrategy` emits
   structured `Signal`s (it never places orders).
4. Every signal passes through `RiskEngine`/`RiskLimits` (daily loss limit,
   weekly drawdown, consecutive losses, open positions, entries/day, sizing,
   kill switch). Rejected signals are terminal.
5. Risk-approved signals become **`pending` proposals**. The operator
   approves (fills via paper broker after risk re-check at the live price) or
   rejects them. With `auto_approve`, pending proposals execute immediately.
6. All events stream to WebSocket dashboards and (optionally) mirror into SQL.

### Safety model

- Paper mode default; stop-loss required (config `require_stop_loss`).
- Live mode demands verified instrument metadata and still cannot place real
  orders (v1 scope).
- The API binds to `127.0.0.1` by default. **There is no authentication** —
  do not expose the port to a network.
- The database sink is defensive: any DB failure disables mirroring instead
  of interrupting the trading loop.

---

## Quick start

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make db        # sync locked deps incl. dev + db extras (creates .venv)
make check     # ruff + mypy + full pytest suite (expect: all green)
```

Run the whole stack (backend on :8000 with the built dashboard, or the Vite
dev server on :5173 proxying to it):

```bash
./start_goldbot.sh --backend   # start backend in the background
./start_goldbot.sh --status    # health / PID info
./start_goldbot.sh --stop      # stop it
./start_goldbot.sh --check     # static validation only
```

Then open <http://127.0.0.1:8000>. The engine replays bundled sample data
(`data/fixtures/sample_xauusd_15m.csv`), so signals and fills appear quickly.
Environment knobs (see `start_goldbot.sh` header):

- `GOLDBOT_CSV_PATH` — custom candle CSV
- `GOLDBOT_AUTO_APPROVE=1` — execute risk-approved proposals automatically
- `GOLDBOT_REPLAY_INTERVAL` — seconds between replay bars (default 1.0)
- `GOLDBOT_START_LOOP=0` — boot with the replay loop paused
- `GOLDBOT_RELOAD=0` — disable uvicorn auto-reload

### CLI

```bash
uv run goldbot config-check        # validate settings
uv run goldbot paper --bars 120    # terminal paper session
uv run goldbot backtest run        # replay full dataset, print performance
uv run goldbot data-status         # inspect the CSV dataset
```

### Dashboard pages

Overview · Live market (candles + EMAs) · Trade approval (pending/decided
proposals) · Open positions · Trade history · Performance analytics · System
health (kill switch, risk limits) · Bot configuration (live-safe updates).

---

## Database (optional)

Paper sessions work fully without a database (JSON ledger in
`logs/orders_<symbol>.json`). To enable SQL mirroring of proposals, orders,
fills, closed trades and kill-switch events:

```bash
sudo -u postgres psql -c "CREATE ROLE goldbot LOGIN PASSWORD '...';"
sudo -u postgres psql -c "CREATE DATABASE goldbot OWNER goldbot;"
export GOLD_DATABASE_URL="postgresql+psycopg://goldbot:...@localhost:5432/goldbot"
alembic upgrade head              # apply the schema
./start_goldbot.sh --backend
```

`alembic upgrade head` builds all 14 tables; `alembic downgrade base`
removes them. SQLite works as well for experiments:
`GOLD_DATABASE_URL="sqlite+pysqlite:///dev_goldbot.sqlite3" alembic upgrade head`.

Schema is managed by Alembic only; `Base.metadata.create_all` exists purely
for tests. DB tests (ORM CRUD, migrations, sink round-trips) live in
`tests/test_database.py` and use SQLite; the PostgreSQL path is verified
per `docs/PROGRESS.md`.

---

## Configuration

Settings live in `config/settings.yaml` (defaults) and may be overridden by
environment variables with the `GOLD_` prefix (e.g. `GOLD_MODE`),
documented in `.env.example`. Notable defaults: `mode: paper`, 1% daily /
3% weekly loss limits, 0.25% risk per trade, max 1 open position and 3
entries per day, spread 0.1 / slippage 0.5 simulation assumptions
(contract size 100 oz/lot, explicit paper-mode assumptions in code).

---

## Testing & quality gates

```bash
make test        # 148 tests: engine, strategy, indicators, risk, broker,
                 # CSV, config, API, WebSocket, operator flow, DB round-trips
make lint        # ruff (clean)
make type-check  # mypy (clean)
make check       # all of the above
```

Frontend: `cd frontend && npm run build` (tsc strict + vite build).
End-to-end and manual verification commands are recorded in
`docs/PROGRESS.md`; the acceptance matrix is `docs/TEST_PLAN.md`.

---

## Known limitations

- No live broker adapter (by design, v1), no live market-data feed — CSV
  replay only.
- No authentication/authorization on the dashboard API (local bind only).
- Paper fills are simulated assumptions; correlations with real execution
  quality are not implied.
- A restored JSON ledger after replay restart can immediately close a stale
  open position at the first bar (by design the tape wraps); delete
  `logs/orders_XAUUSD.json` for a clean session.
- Backtest runner (`backtest run`) walks the tape linearly; metrics are
  indicative, not strategy research.

See `docs/PROGRESS.md` for the historical engineering log.
