#!/usr/bin/env bash
#
# GoldBot — single-command startup.
#
# Usage (from the project root):
#   ./start.sh              # backend + frontend (foreground)
#   ./start.sh --backend    # backend only (detached, port 8000)
#   ./start.sh --check      # dependency validation
#   ./start.sh --status     # process status
#   ./stop.sh               # graceful shutdown
#
# This wrapper delegates to start_goldbot.sh, the full startup manager:
# it validates dependencies, loads .env, applies database migrations,
# starts backend (FastAPI/uvicorn) and frontend (Vite), verifies readiness,
# detects port conflicts, prevents duplicate processes, and logs to
# $GOLDBOT_BACKEND_LOG (default /tmp/goldbot.log).
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ ! -f "$ROOT/start_goldbot.sh" ]]; then
  echo "error: start_goldbot.sh not found next to start.sh" >&2
  exit 1
fi

exec "$ROOT/start_goldbot.sh" --root "$ROOT" "$@"
