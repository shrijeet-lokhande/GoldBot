# AGENTS.md — repository conventions for automated contributors

Scope: instructions for AI agents / automated tooling working in this
repository. Human contributors may ignore this file.

## Project identity

- Product: GoldBot — XAUUSD (gold spot) analysis & execution platform.
- The primary instrument is defined in exactly one place:
  `src/goldbot/core/instruments.py` (`PRIMARY_INSTRUMENT`, canonical symbol
  `XAUUSD`, TradingView `OANDA:XAUUSD`, OANDA `XAU_USD`). Never hardcode a
  symbol fallback in service code; import `PRIMARY_INSTRUMENT`.
- Backend: Python 3.12, FastAPI, SQLAlchemy + Alembic, pandas/numpy,
  managed with `uv` (`.venv/`). Frontend: React + Vite + TypeScript strict.

## Hard rules

1. **Do not rebuild.** Continue from the existing implementation; preserve
   completed work. Check `context.txt` (handoff state) before starting.
2. **Paper/live isolation.** Never send paper orders to a live endpoint or
   vice versa. Live mode requires the exact authorization phrase
   `ENABLE LIVE TRADING` plus a connected broker; do not weaken that gate.
3. **Secrets.** Never write tokens/keys/passwords into code, tests,
   context.txt, docs, or commits. Credentials come only from `GOLD_*`
   environment variables. `.env` is gitignored.
4. **Database migrations are additive only.** Never drop columns/tables or
   delete data. Never relabel historical records to a different instrument;
   provenance columns record what a row was stored as.
5. **No look-ahead.** Analysis/prediction consume completed candles only;
   feature rows at time t must not depend on data after t. Chronological
   splits for any evaluation — never shuffle time series.
6. **Confidence ≠ probability.** Heuristic confidence scores must carry the
   explicit non-probability disclaimer. Only calibrated metrics (Brier,
   calibration bins) describe probabilistic quality.
7. **Numeric thresholds need rationale.** Every new constant used by a
   detection rule or guard gets an entry in `docs/THRESHOLDS.md`.
8. **Spec-driven sizing.** Live position sizing must use broker-fetched
   contract specs (`instrument_spec_from_oanda`); reject trades when specs
   are missing or inconsistent rather than assuming values.

## Commands (run from the repo root)

```bash
uv run pytest -q               # backend tests (~250)
uv run ruff check src tests scripts   # lint (clean required)
uv run mypy src/goldbot        # types (clean required)
cd frontend && npm run build   # tsc strict + vite build (clean required)
./start.sh [--backend|--check|--status]   # services; ./stop.sh halts
uv run python scripts/e2e_live.py         # 15-check E2E (backend running)
```

Note: the full pytest suite takes ~4–6 minutes; use a generous timeout.

## Conventions

- Commits: imperative, one milestone per commit; update `context.txt`
  phase statuses (PLANNED / IN PROGRESS / DONE only after verification)
  in a follow-up checkpoint commit.
- Tests live in `tests/`, named by domain (`test_<area>.py`). New backend
  behavior requires tests; broker integration tests use a scripted
  `http` transport — never real network calls in CI.
- Python: `from __future__ import annotations`, typed functions, module
  docstrings explaining the why (not the what). Ruff + mypy must pass.
- Frontend: TypeScript strict; components fetch instrument identity from
  `/api/v1/instrument` instead of hardcoding symbols; displayed market
  data must show its source label and timestamp.
- Logs and runtime artifacts (`logs/`, `.run/`, `*.db3`) are gitignored;
  never commit them.

## Context management

`context.txt` at the repo root is the cross-session handoff file. Update
it after every significant milestone; it must never contain secrets and
must never be overwritten with unverified status (do not pre-mark DONE).
The runtime cannot inspect its true context window, so the working rule
is: checkpoint after each completed phase and at any natural stopping
point; do not pretend to clear context.
