"""GoldBot FastAPI application - main backend entry point.

Serves the trading engine over REST (/api/v1/...) and a live WebSocket
(/ws). When a built frontend exists (frontend/dist), it is served at "/"
so the whole application runs from a single port.

Environment knobs:
    GOLDBOT_CSV_PATH         CSV data file for the engine candle replay
    GOLDBOT_AUTO_APPROVE     "1" to auto-execute risk-approved proposals
    GOLDBOT_REPLAY_INTERVAL  seconds between replay bars (default 1.0)
    GOLDBOT_START_LOOP       "0" to boot with the replay loop paused
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from goldbot.core.config import GoldBotSettings, load_settings
from goldbot.core.exceptions import GoldBotError
from goldbot.engine import TradingEngine

logger = logging.getLogger("goldbot.api.app")

# ---------------------------------------------------------------------------
# Globals (initialised in lifespan)
# ---------------------------------------------------------------------------

engine: TradingEngine | None = None
settings: GoldBotSettings | None = None
db_sink = None  # goldbot.database.repository.DatabaseSink | None
_mode_mgr = None  # goldbot.execution.mode_manager.TradingModeManager | None
_broker = None  # goldbot.execution.oanda.OandaBrokerAdapter | None

ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"


class EventBroker:
    """Fan-out engine events to attached WebSocket clients."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._unsubscribe: Callable[[], None] | None = None

    def bind(self, trading_engine: TradingEngine) -> None:
        def _on_event(event: dict) -> None:
            for queue in list(self._queues):
                if queue.full():
                    # Slow client: drop the oldest event instead of blocking
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(event)

        if self._unsubscribe is not None:
            self._unsubscribe()
        self._unsubscribe = trading_engine.subscribe(_on_event)

    def attach(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2048)
        self._queues.add(queue)
        return queue

    def detach(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    @property
    def client_count(self) -> int:
        return len(self._queues)


event_broker = EventBroker()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the engine (and its replay loop) with the application."""
    global engine, settings
    settings = load_settings(_config_path())
    csv_path = os.environ.get("GOLDBOT_CSV_PATH")
    persistence = os.environ.get("GOLDBOT_PERSISTENCE_PATH")
    auto_approve = os.environ.get("GOLDBOT_AUTO_APPROVE", "0") in ("1", "true", "yes")
    engine = TradingEngine(
        settings,
        csv_path=Path(csv_path) if csv_path else None,
        auto_approve=auto_approve,
        persistence_path=Path(persistence) if persistence else None,
    )
    event_broker.bind(engine)

    # Optional database mirror: only active when a database URL is set.
    global db_sink
    try:
        from goldbot.database.repository import attach_sink

        db_sink = attach_sink(engine, settings)
    except Exception:
        logger.exception("Failed to attach the optional database sink")

    logger.info(
        "Engine ready: %s %s bars=%d auto_approve=%s",
        engine.symbol,
        settings.mode,
        len(engine._all_candles),
        auto_approve,
    )
    if os.environ.get("GOLDBOT_START_LOOP", "1") not in ("0", "false"):
        interval = float(os.environ.get("GOLDBOT_REPLAY_INTERVAL", "1.0"))
        engine.run_background(interval_seconds=interval)
    try:
        yield
    finally:
        if engine is not None:
            engine.stop_background()
            engine.save_state()
            logger.info("Engine stopped, state saved")
        if db_sink is not None:
            db_sink.close()


def _config_path() -> str:
    return os.environ.get("GOLDBOT_CONFIG", "config/settings.yaml")


def _engine() -> TradingEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="engine not initialised")
    return engine


def _mode_manager():
    """Lazily constructed trading-mode manager (paper default, audited)."""
    global _mode_mgr
    if _mode_mgr is None:
        from goldbot.execution.mode_manager import TradingModeManager

        _mode_mgr = TradingModeManager()
    return _mode_mgr


def _broker_adapter():
    """OANDA adapter when operator credentials are configured, else None.

    Credentials come from the environment only (GOLD_OANDA_*); they are never
    persisted in the database or logged. Default environment is ``practice``
    (the demo/sandbox host) — ``live`` must be selected explicitly.
    """
    global _broker
    if _broker is None:
        account_id = os.environ.get("GOLD_OANDA_ACCOUNT_ID")
        token = os.environ.get("GOLD_OANDA_API_TOKEN")
        environment = os.environ.get("GOLD_OANDA_ENVIRONMENT", "practice")
        if account_id and token:
            from goldbot.execution.oanda import OandaBrokerAdapter

            _broker = OandaBrokerAdapter(
                account_id=account_id,
                api_token=token,
                environment=environment,
            )
    return _broker


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="GoldBot API",
    description="Paper-trading engine for XAUUSD with operator approval flow",
    version="0.1.0",
    lifespan=lifespan,
)

# Dev-friendly CORS so the Vite dev server can talk to this API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@app.exception_handler(GoldBotError)
async def goldbot_error_handler(_req, exc: GoldBotError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Health / meta
# ---------------------------------------------------------------------------


@app.get("/api/v1/health")
def health() -> dict:
    body = _engine().get_health()
    if settings is not None and settings.database_url:
        body["database"] = {
            "enabled": True,
            "mirroring": bool(db_sink is not None and not db_sink.disabled),
            "rows_written": db_sink.rows_written if db_sink else 0,
        }
    return body


@app.get("/api/v1/instrument")
def instrument() -> dict:
    """Canonical instrument identity + provider symbol mappings."""
    from goldbot.core.instruments import PRIMARY_INSTRUMENT, TRADINGVIEW_CHART_URL

    return {
        "symbol": PRIMARY_INSTRUMENT.symbol,
        "name": PRIMARY_INSTRUMENT.name,
        "asset_type": PRIMARY_INSTRUMENT.asset_type,
        "quote_currency": PRIMARY_INSTRUMENT.quote_currency,
        "tradingview_symbol": PRIMARY_INSTRUMENT.tradingview,
        "tradingview_chart_url": TRADINGVIEW_CHART_URL,
        "oanda_symbol": PRIMARY_INSTRUMENT.symbol_for("oanda"),
        "contract_size": PRIMARY_INSTRUMENT.contract_size,
        "tick_size": PRIMARY_INSTRUMENT.tick_size,
    }


# ---------------------------------------------------------------------------
# XAUUSD analysis engine
# ---------------------------------------------------------------------------


@app.get("/api/v1/analysis")
def analysis(refresh: bool = False) -> dict:
    """Structured XAUUSD analysis report over the revealed candles.

    Deterministic per revealed-candle state; ``refresh`` is accepted for API
    compatibility (reports are recomputed from the same state either way).
    """
    eng = _engine()
    return eng.analyze()


@app.get("/api/v1/prediction")
def prediction(horizon: int = 4) -> dict:
    """XAUUSD statistical forecast with honest, out-of-sample validation.

    Returns the 10-field forecast (bias, regime, entry/invalidation/stop/TP,
    risk-reward, horizon, heuristic confidence, evidence) plus the evaluation
    block (chronological-split accuracy vs baselines, walk-forward, Brier,
    calibration). Confidence is a heuristic score, NOT a calibrated
    probability — the evaluation block is where real skill is shown.
    """
    if horizon < 1 or horizon > 32:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="horizon must be between 1 and 32 bars")
    eng = _engine()
    candles = eng.candles
    from goldbot.prediction import run_prediction

    try:
        return run_prediction(candles, horizon_bars=horizon).to_dict()
    except ValueError as exc:
        # Insufficient revealed history: state the limitation instead of
        # manufacturing a forecast.
        return {
            "available": False,
            "detail": str(exc),
            "data_limitation": (
                "Not enough completed XAUUSD candles are revealed yet. The "
                "prediction pipeline refuses to fit or forecast on thin data."
            ),
        }


# ---------------------------------------------------------------------------
# Trading mode (paper/live) management
# ---------------------------------------------------------------------------


@app.get("/api/v1/mode")
def mode_status() -> dict:
    return _mode_manager().status()


@app.post("/api/v1/mode/authorize-live")
def mode_authorize_live(payload: dict) -> dict:
    result = _mode_manager().authorize_live(
        confirmation=str((payload or {}).get("confirmation", "")),
        actor=str((payload or {}).get("actor", "operator")),
    )
    if not result.get("authorized"):
        raise HTTPException(status_code=403, detail=result.get("reason"))
    return _mode_manager().status()


@app.post("/api/v1/mode/switch")
def mode_switch(payload: dict) -> dict:
    result = _mode_manager().switch_mode(
        str((payload or {}).get("mode", "")),
        actor=str((payload or {}).get("actor", "operator")),
    )
    if result.get("status") == "denied":
        raise HTTPException(status_code=403, detail=result.get("reason"))
    return result


@app.get("/api/v1/mode/audit")
def mode_audit() -> list[dict]:
    return [e.to_dict() for e in _mode_manager().audit_trail]


# ---------------------------------------------------------------------------
# Broker/account connections
# ---------------------------------------------------------------------------


@app.get("/api/v1/connections")
def connections_status() -> dict:
    mgr = _mode_manager()
    broker = _broker_adapter()
    summary = None
    if broker is not None:
        try:
            summary = broker.get_account_summary()
        except Exception as exc:
            logger.warning("broker account summary failed: %s", exc)
            summary = {"error": str(exc)}
    return {
        "mode": mgr.status(),
        "broker": {
            "adapter": "oanda" if broker is not None else None,
            "environment": broker.environment if broker else None,
            "configured": broker is not None,
            "account_summary": summary,
            # TradingView has no generic OAuth for bots; TV auth is not
            # implemented (and must not be faked).
            "tradingview_oauth_available": False,
        },
    }


@app.post("/api/v1/connections/broker/verify")
def connections_broker_verify() -> dict:
    """Verify broker connectivity with configured credentials (read-only)."""
    broker = _broker_adapter()
    if broker is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "broker not configured: set GOLD_OANDA_ACCOUNT_ID, "
                "GOLD_OANDA_API_TOKEN, GOLD_OANDA_ENVIRONMENT"
            ),
        )
    ok = broker.health_check()
    _mode_manager().set_broker_connection(ok, detail=f"oanda:{broker.environment}")
    return {
        "connected": ok,
        "environment": broker.environment,
        "account_summary": broker.get_account_summary() if ok else None,
    }


@app.get("/api/v1/config")
def get_config() -> dict:
    cfg = _engine().get_config()
    cfg["api_version"] = app.version
    return cfg


@app.post("/api/v1/config")
def update_config(payload: dict) -> dict:
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="config values required")
    return _engine().update_config(payload)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


@app.get("/api/v1/quote")
def quote() -> dict:
    return _engine().get_quote()


@app.get("/api/v1/indicators")
def indicators() -> dict:
    return _engine().get_indicators()


@app.get("/api/v1/candles")
def candles(limit: int = Query(default=300, ge=1, le=5000)) -> dict:
    eng = _engine()
    revealed = eng.candles[-limit:]
    timeframe = eng.entry_timeframe
    out = {}
    for name in ("ema_fast", "ema_trend", "ema_long"):
        series = eng.get_indicators().get("series", {}).get(name) or []
        offset = len(revealed) - len(series)
        aligned = series[offset:] if offset > 0 else series[: len(revealed)]
        out[name] = aligned[-len(revealed) :] if revealed else []
    return {
        "symbol": eng.symbol,
        "timeframe": timeframe,
        "candles": [
            {
                "time": int(c.timestamp_utc.timestamp()),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in revealed
        ],
        "indicators": out,
        "replay_index": eng._replay_index,
        "total_bars": len(eng._all_candles),
    }


# ---------------------------------------------------------------------------
# Account / positions / trades / orders
# ---------------------------------------------------------------------------


@app.get("/api/v1/account")
def account() -> dict:
    return _engine().get_account()


@app.get("/api/v1/positions")
def positions() -> list[dict]:
    return _engine().get_positions()


@app.post("/api/v1/positions/close")
def positions_close(payload: dict | None = None) -> dict:
    symbol = (payload or {}).get("symbol")
    eng = _engine()
    result = eng.close_position(symbol)
    if result.get("status") == "no_open_position":
        raise HTTPException(status_code=404, detail="no open position")
    return result


@app.get("/api/v1/trades")
def trades(limit: int = Query(default=50, ge=1, le=1000)) -> list[dict]:
    return _engine().get_trades(limit=limit)


@app.get("/api/v1/orders")
def orders() -> list[dict]:
    return _engine().get_orders()


@app.get("/api/v1/performance")
def performance() -> dict:
    return _engine().get_performance()


# ---------------------------------------------------------------------------
# Trade proposals (operator approval flow)
# ---------------------------------------------------------------------------


@app.get("/api/v1/proposals")
def proposals(status: str | None = None) -> list[dict]:
    return _engine().get_proposals(status=status)


@app.post("/api/v1/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str) -> dict:
    result = _engine().approve_proposal(proposal_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="proposal not found")
    return result


@app.post("/api/v1/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, payload: dict | None = None) -> dict:
    reason = (payload or {}).get("reason", "operator_rejected")
    result = _engine().reject_proposal(proposal_id, reason)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="proposal not found")
    return result


# ---------------------------------------------------------------------------
# Risk controls
# ---------------------------------------------------------------------------


@app.post("/api/v1/risk/kill-switch")
def kill_switch(payload: dict) -> dict:
    eng = _engine()
    active = bool(payload.get("active", True))
    reason = str(payload.get("reason", "manual")) if active else "manual"
    eng.set_kill_switch(active, reason)
    return eng.get_health()


@app.get("/api/v1/risk/limits")
def risk_limits() -> dict:
    eng = _engine()
    return {
        "risk_per_trade_pct": eng.risk_limits.risk_per_trade_pct,
        "daily_loss_limit_pct": eng.risk_limits.daily_loss_limit_pct,
        "weekly_drawdown_limit_pct": eng.risk_limits.weekly_drawdown_limit_pct,
        "max_open_positions": eng.risk_limits.max_open_positions,
        "max_entries_per_day": eng.risk_limits.max_entries_per_day,
        "max_consecutive_losses": eng.risk_limits.max_consecutive_losses,
        "entries_today": eng.risk_limits._entries_today,
        "consecutive_losses": eng.risk_limits.consecutive_losses,
        "start_of_day_equity": eng.risk_limits._start_of_day_equity,
        "weekly_equity_high": eng.risk_limits._weekly_equity_high,
        "kill_switch": eng.kill_switch.reasons,
    }


# ---------------------------------------------------------------------------
# Engine control
# ---------------------------------------------------------------------------


@app.post("/api/v1/engine/start")
async def engine_start(payload: dict | None = None) -> dict:
    eng = _engine()
    interval = float((payload or {}).get("interval_seconds", 1.0))
    eng._loop_task = eng.run_background(interval_seconds=max(0.05, interval))
    return {
        "status": "started",
        "running": True,
        "interval_seconds": interval,
        "health": eng.get_health(),
    }


@app.post("/api/v1/engine/stop")
def engine_stop() -> dict:
    eng = _engine()
    eng.stop_background()
    return {"status": "stopped", "running": False, "health": eng.get_health()}


@app.get("/api/v1/engine/status")
def engine_status() -> dict:
    eng = _engine()
    return {
        "running": eng._running,
        "replay_index": eng._replay_index,
        "total_bars": len(eng._all_candles),
        "auto_approve": eng.auto_approve,
        "websocket_clients": event_broker.client_count,
    }


# ---------------------------------------------------------------------------
# WebSocket stream
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    queue = event_broker.attach()

    # Prime the client with the current snapshot so it renders instantly.
    eng = _engine()
    await ws.send_json(
        {
            "type": "snapshot",
            "data": {
                "health": eng.get_health(),
                "quote": eng.get_quote(),
                "account": eng.get_account(),
                "positions": eng.get_positions(),
                "proposals": eng.get_proposals(status="pending"),
                "candles": [
                    {
                        "time": int(c.timestamp_utc.timestamp()),
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in eng.candles[-300:]
                ],
                "indicators": eng.get_indicators(),
            },
        }
    )

    try:
        while True:
            # Concurrent: await incoming control messages and outgoing events.
            incoming = asyncio.create_task(ws.receive_text())
            outgoing = asyncio.create_task(queue.get())
            try:
                done, pending = await asyncio.wait(
                    {incoming, outgoing},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    if task is incoming:
                        _handle_ws_control(eng, task.result())
                    else:
                        event = task.result()
                        await ws.send_json(event)
            except asyncio.CancelledError:
                raise
            finally:
                for task in (incoming, outgoing):
                    if not task.done():
                        task.cancel()
        # Loop exits on disconnect; fall through to cleanup.
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket session failed")
    finally:
        event_broker.detach(queue)


def _handle_ws_control(eng: TradingEngine, message: str) -> None:
    """Handle simple control messages sent over the WebSocket."""
    if message == "ping":
        return  # deploy a pong via the send loop? engine is read-only here
    if message == "start":
        eng.run_background()
    elif message == "stop":
        eng.stop_background()


# ---------------------------------------------------------------------------
# Frontend serving (single-port deployment)
# ---------------------------------------------------------------------------

if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets"), check_dir=False),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # API/WS namespaces must 404 with JSON - never fall back to the SPA.
        if full_path == "api" or full_path.startswith("api/") or full_path.startswith("api/v1/"):
            raise HTTPException(status_code=404, detail="not found")
        # Serve real files (favicon etc.), then SPA-fallback to index.html
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and str(candidate).startswith(str(FRONTEND_DIST)) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
