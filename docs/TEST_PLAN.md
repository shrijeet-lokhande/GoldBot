# GoldBot — Acceptance Test Matrix

The acceptance criteria below are derived from the project's own
documented intent (engine/broker/risk docstrings, `config/settings.yaml`,
`.env.example`, the API surface in `src/goldbot/api/app.py`, and the
dashboard pages in `frontend/src`). Every criterion has a measurable
pass/fail condition. Update the Status column as evidence is gathered.

| # | Feature | Expected behavior | Preconditions | Test inputs / method | Pass condition | Status |
|---|---------|-------------------|---------------|----------------------|----------------|--------|
| A1 | Configuration validation | Invalid config (bad mode, non-positive risk, live mode without verified metadata) is rejected; valid YAML loads | none | `pytest tests/test_config.py`; `goldbot config-check` | all assertions pass; CLI exits 0 | ✅ |
| A2 | CSV data ingestion | Malformed CSV (bad columns, non-numeric OHLC, broken candles) raises `DataError`; valid CSV yields sorted UTC candles | fixture CSV | `pytest tests/test_csv_provider.py` | all assertions pass | ✅ |
| A3 | Indicators | EMA/RSI/ATR/ADX computed correctly incl. warm-up NaN phase | none | `pytest tests/test_indicators.py` | all assertions pass | ✅ |
| A4 | Trend-pullback strategy | Emits LONG/SHORT signals only for valid setups, one signal per candle (no duplicates), none when insufficient history | synthetic candles | `pytest tests/test_strategy.py` | all assertions pass | ✅ |
| A5 | Paper broker | Market/limit fills include spread+slippage; SL/TP trigger intrabar; positions/durations tracked; persistence survives reload | none | `pytest tests/test_paper_broker.py` | all assertions pass | ✅ |
| A6 | Position sizing | Size = (equity × risk%) ÷ (stop distance × contract value); respects min/max volume | verified metadata | `pytest tests/test_position_sizing.py` | all assertions pass | ✅ |
| A7 | Risk engine independence | Rejects on kill switch, unverified metadata, daily/weekly loss limits, consecutive losses, open-position cap, entries/day cap | mixed | `pytest tests/test_risk_engine.py tests/test_risk_limits.py` | all assertions pass | ✅ |
| A8 | Nothing bypasses risk engine | Every executed order originates from a risk-approved proposal; paper mode requires SL | engine running | `pytest tests/test_engine.py` | all assertions pass | ✅ |
| A9 | Operator approval flow | Risk-approved proposals enter `pending`; operator approve executes through risk re-check; reject marks rejected; rejected proposals cannot execute | engine, auto_approve off | API: `POST /api/v1/proposals/{id}/approve|reject`; `pytest tests/test_api.py::test_proposal_lifecycle_end_to_end` | lifecycle statuses observed; no order without approval | ✅ done |
| A10 | REST API completeness | All documented endpoints return expected shapes/errors incl. 404s | backend up | `pytest tests/test_api.py`; manual curl sweep | all assertions pass | ✅ |
| A11 | WebSocket stream | `/ws` sends snapshot immediately and candle/price/proposal/order events live | engine stepping | `pytest tests/test_api.py::test_websocket_snapshot_and_events` | all assertions pass | ✅ |
| A12 | Frontend type-check & build | `tsc -b` clean; `vite build` produces `dist/` | node_modules | `cd frontend && npm run build` | exit 0, dist exists | ✅ done |
| A13 | Single-port deployment | Backend serves built SPA at `/`, API at `/api/v1/*`, WS at `/ws` | dist exists | start backend, curl `/`, `/api/v1/health`, WS probe, asset check | HTTP 200s, SPA fallback works | ✅ done |
| A14 | Live data flow (smoke) | With loop running, paper session produces quotes, proposals, trades; equity updates, persist state | dataset | `goldbot paper --bars 120`; then inspect logs/orders file | trades ≥ 0, no crash, persistence file valid JSON | ✅ done |
| A15 | Backtest reproducibility | `goldbot backtest run` completes over full dataset and reports performance metrics | dataset | CLI run | exit 0, metrics printed | ✅ done |
| A16 | Live-mode safety gates | Live mode without verified metadata or symbol information is rejected at config load | env vars | `pytest tests/test_config.py` (live guards) | all assertions pass | ✅ |
| A17 | Database schema migrations | `alembic upgrade head` creates all tables; `head` idempotent; revised schema matches ORM models | DB available | run Alembic vs SQLite & PostgreSQL; reflect tables | all ORM tables present | ✅ done |
| A18 | Database ORM operations | Insert/fetch representative ORM rows (order, position, trade, proposal, event) round-trip correctly | migrated DB | pytest DB integration tests | round-trip equality | ✅ done |
| A19 | Linting | `ruff check .` returns no findings | ruff installed | `make lint` | exit 0 | ✅ done |
| A20 | Type checking | `mypy .` returns no errors (per configured strictness) | mypy installed | `make type-check` | exit 0 | ✅ done |
| A21 | Dependency lockfile | `uv sync --frozen` succeeds; `uv.lock` committed | lock exists | `make install` (or `uv sync --frozen`) | exit 0 | ✅ done |
| A22 | No secrets committed | Repo contains no credentials; example files use placeholders | — | grep for hardcoded credentials | only placeholders found | ✅ done |
| A23 | Regression safety | Full suite passes after every change | — | `pytest` / `make check` | all tests green; re-run after each change | ✅ final run: 148 passed |

## Notes on method
- Backend tests run against the actual FastAPI app with `TestClient`, real
  engine loops disabled for determinism (`GOLDBOT_START_LOOP=0`).
- Real end-to-end verification (A13/A14/A15) is executed outside pytest by
  actually starting the server and curling it; commands recorded in
  `docs/PROGRESS.md`.
- Database criteria (A17/A18) verified against SQLite (CI-friendly) and
  PostgreSQL (declared target in `.env.example` / `alembic.ini`).
