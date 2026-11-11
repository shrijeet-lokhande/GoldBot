# GoldBot

Algorithmic **XAUUSD (gold spot)** trading platform: candle-replay trading
engine, independent risk engine, transparent statistical prediction
pipeline, market-structure analysis engine, paper broker, OANDA v20 live
adapter (practice default), FastAPI backend (REST + WebSocket), React
operator dashboard, and Alembic-managed persistence.

Primary instrument: **XAUUSD** (internal symbol), `OANDA:XAUUSD`
(TradingView display reference), `XAU_USD` (OANDA execution symbol).
The symbol mapping lives in one place: `src/goldbot/core/instruments.py`.

> **Status:** functional and tested — 253+ backend tests, ruff/mypy clean,
> frontend tsc strict + vite build clean, E2E 15/15. Paper mode is the
> default and safe mode; live trading requires an explicit, deliberate
> authorization phrase and configured OANDA practice/live credentials.

---

## Quick start

```bash
# 1. Dependencies (Python 3.12 + uv; Node 18+ for the dashboard)
uv sync                      # backend deps -> .venv
cd frontend && npm ci && cd ..  # dashboard deps

# 2. Configure (optional; paper mode works with defaults)
cp .env.example .env         # never commit .env — no secrets go to git

# 3. Run
./start.sh                   # backend (127.0.0.1:8000) + frontend (5173)
./start.sh --backend         # backend only, detached
./start.sh --check           # validate environment
./stop.sh                    # graceful shutdown
```

The backend serves the built dashboard at
`http://127.0.0.1:8000/` when `frontend/dist` exists; otherwise use the
Vite dev server (`./start.sh` foreground mode proxies `/api` + `/ws`).

Dashboard pages: Overview · Live market · TradingView · Prediction ·
Analysis · Trade approval · Open positions · Trade history · Performance ·
Configuration · Mode & accounts · System health.

---

## Architecture

```
src/goldbot/
├── core/          config (pydantic), domain models, instruments identity,
│                  exceptions, clock, logging
├── market_data/   CSV provider, normalizer, validators (UTC normalization)
├── indicators/    EMA, SMA, RSI (exact Wilder), ATR (exact Wilder), ADX,
│                  MACD, Bollinger, StochRSI (+ shared wilder.py recursion)
├── analysis/      multi-timeframe analysis engine, market structure
│                  (BOS/CHOCH/sweeps/FVG/OB/consolidations), session & PD/PW
│                  reference levels, macro-data provider interface
├── prediction/    XAUUSD prediction pipeline: no-lookahead features,
│                  transparent logistic model, baselines, chronological
│                  split + walk-forward validation, Brier + calibration,
│                  10-field forecast
├── strategies/    trend_pullback (multi-timeframe, candle-close only)
├── risk/          RiskEngine (independent gate), limits, kill switch,
│                  spec-driven position sizing
├── execution/     PaperBroker (spread/slippage/SL/TP + JSON ledger),
│                  OandaBrokerAdapter (v20 REST, broker-verified contract
│                  specs, spec-driven sizing)
├── backtest/      linear-tape metrics runner
├── database/      SQLAlchemy ORM, Alembic migrations (additive only),
│                  optional mirror of engine events
├── api/           FastAPI: /api/v1/* (health, instrument, quote, candles,
│                  indicators, analysis, prediction, proposals, orders,
│                  positions, trades, config, mode, connections), /ws
└── engine.py      TradingEngine: replay loop, proposals, approval lifecycle

frontend/          React + Vite dashboard (12 pages)
migrations/        Alembic environment + revisions (all additive)
config/            settings.yaml
docs/              THRESHOLDS.md (every numeric constant's rationale),
                   TEST_PLAN.md, PROGRESS.md
scripts/           e2e_live.py (15-check E2E), fetch_history.py (data
                   acquisition from OANDA practice REST)
data/              fixtures/sample_xauusd_15m.csv (only dataset present)
```

### Data flow

1. `CsvMarketDataProvider` loads historical 15m candles (validated, UTC).
2. `TradingEngine` replays them bar-by-bar (configurable speed, wraps at
   the tape end); only completed candles are ever analyzed.
3. Strategy + analysis/prediction engines read revealed candles only
   (no look-ahead); proposals go to the operator dashboard.
4. `RiskEngine` independently validates size/exposure/limits before the
   `PaperBroker` (or, after explicit live authorization, the OANDA
   adapter with broker-verified contract specs) executes.
5. Orders/positions/trades can mirror to the database (Alembic schema).

---

## Configuration

`config/settings.yaml` (defaults) overridden by `GOLD_`-prefixed
environment variables (see `.env.example`). Notable defaults: paper mode,
0.25% risk per trade, live-trading safeguards (0.5%/trade hard cap, 2%
daily loss, max 2 positions, spread/ATR/data-age guards — all rationale in
`docs/THRESHOLDS.md`). OANDA credentials via
`GOLD_OANDA_ACCOUNT_ID` / `GOLD_OANDA_API_TOKEN` / `GOLD_OANDA_ENVIRONMENT`
(practice default) — never commit real tokens.

---

## Testing & quality gates

```bash
make test        # backend suite (250+ tests)
make lint        # ruff
make type-check  # mypy
make check       # all of the above
cd frontend && npm run build   # tsc strict + vite
uv run python scripts/e2e_live.py   # 15-check E2E (backend must be running)
uv run python scripts/fetch_history.py --status   # data coverage + limitation
```

---

## Known limitations

- Historical data: only 1,510 × 15m bars (~15.7 days). Prediction accuracy
  figures are computed honestly out-of-sample within that window but must
  not be read as general claims; `scripts/fetch_history.py` extends the
  dataset (OANDA practice credentials required).
- Prediction confidence is a bounded heuristic, not a calibrated
  probability — the API/UX state this explicitly.
- Live execution requires operator-supplied OANDA credentials and an
  explicit `ENABLE LIVE TRADING` authorization; without them it is
  structurally unreachable.
- No authentication on the dashboard API (local bind only).
- Paper fills simulate spread/slippage; correlations with real execution
  quality are not implied.
- Backtest runner walks the tape linearly; metrics are indicative.

See `docs/THRESHOLDS.md` for constant rationale, `docs/TEST_PLAN.md` for
the acceptance matrix, `docs/PROGRESS.md` for the engineering log, and
`AGENTS.md` for repository conventions for automated contributors.
