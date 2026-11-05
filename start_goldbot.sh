#!/usr/bin/env bash
#
# GoldBot startup manager
#
# Usage (from the repository root):
#   chmod +x ./start_goldbot.sh
#   ./start_goldbot.sh --check
#   ./start_goldbot.sh --backend
#   ./start_goldbot.sh
#   ./start_goldbot.sh --status
#   ./start_goldbot.sh --stop
#
# The default mode starts the backend and frontend. Press Ctrl+C to stop
# the frontend and the backend started by this invocation.
#
set -Eeuo pipefail

SCRIPT_NAME="$(basename -- "${BASH_SOURCE[0]}")"
ROOT_OVERRIDE="${GOLDBOT_ROOT:-}"
MODE="full"

BACKEND_HOST="${GOLDBOT_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${GOLDBOT_BACKEND_PORT:-8000}"
FRONTEND_HOST="${GOLDBOT_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${GOLDBOT_FRONTEND_PORT:-5173}"
ASGI_APP="${GOLDBOT_ASGI_APP:-goldbot.api.app:app}"
HEALTH_URL="${GOLDBOT_HEALTH_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}/api/v1/health}"
BACKEND_LOG="${GOLDBOT_BACKEND_LOG:-/tmp/goldbot.log}"
RELOAD="${GOLDBOT_RELOAD:-1}"
STARTUP_TIMEOUT="${GOLDBOT_STARTUP_TIMEOUT:-30}"

BACKEND_PID=""
FRONTEND_PID=""
BACKEND_STARTED_BY_THIS_RUN=0
FRONTEND_STARTED_BY_THIS_RUN=0
ROOT=""

usage() {
  cat <<EOF
${SCRIPT_NAME} - start and manage the GoldBot development environment

Usage:
  ./${SCRIPT_NAME} [--check | --backend | --status | --stop | --help]
  ./${SCRIPT_NAME} --root /path/to/goldbot [mode]

Modes:
  (no option)  Start backend + frontend. Ctrl+C stops processes started here.
  --check      Validate project files, Python imports and frontend package config.
  --backend    Start backend only, detached in the background.
  --status     Show backend/frontend status.
  --stop       Stop the backend recorded by this script.
  --help       Show this help.

Environment overrides:
  GOLDBOT_ROOT                 Project root (alternative to --root)
  GOLDBOT_BACKEND_HOST         Default: 127.0.0.1
  GOLDBOT_BACKEND_PORT         Default: 8000
  GOLDBOT_FRONTEND_HOST        Default: 127.0.0.1
  GOLDBOT_FRONTEND_PORT        Default: 5173
  GOLDBOT_ASGI_APP             Default: goldbot.api.app:app
  GOLDBOT_HEALTH_URL           Default: http://127.0.0.1:8000/api/v1/health
  GOLDBOT_BACKEND_LOG          Default: /tmp/goldbot.log
  GOLDBOT_RELOAD               Default: 1 (enable Uvicorn reload)
  GOLDBOT_STARTUP_TIMEOUT      Default: 30 seconds

Expected project files:
  .venv/bin/activate
  src/goldbot/api/app.py
  frontend/package.json
EOF
}

log() { printf '[GoldBot] %s\n' "$*"; }
warn() { printf '[GoldBot] WARNING: %s\n' "$*" >&2; }
die() { printf '[GoldBot] ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --root)
      (($# >= 2)) || die "--root requires a directory path."
      ROOT_OVERRIDE="$2"
      shift 2
      ;;
    --check|--backend|--status|--stop)
      [[ "$MODE" == "full" ]] || die "Only one mode may be selected."
      MODE="${1#--}"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1 (use --help for usage)."
      ;;
  esac
done

resolve_root() {
  local script_dir cwd
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  cwd="$(pwd -P)"

  if [[ -n "$ROOT_OVERRIDE" ]]; then
    [[ -d "$ROOT_OVERRIDE" ]] || die "Project root does not exist: $ROOT_OVERRIDE"
    ROOT="$(cd -- "$ROOT_OVERRIDE" && pwd -P)"
  elif [[ -f "$script_dir/src/goldbot/api/app.py" ]]; then
    ROOT="$script_dir"
  elif [[ -f "$cwd/src/goldbot/api/app.py" ]]; then
    ROOT="$cwd"
  else
    die "Could not locate the GoldBot repository. Put this script in the repository root, run it from the repository root, or use --root /path/to/goldbot."
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

check_project_layout() {
  [[ -f "$ROOT/.venv/bin/activate" ]] || die "Python virtual environment not found: $ROOT/.venv/bin/activate"
  [[ -f "$ROOT/src/goldbot/api/app.py" ]] || die "Backend entrypoint not found: $ROOT/src/goldbot/api/app.py"
  if [[ "$MODE" == "full" || "$MODE" == "check" || "$MODE" == "status" ]]; then
    [[ -f "$ROOT/frontend/package.json" ]] || die "Frontend package.json not found: $ROOT/frontend/package.json"
  fi
}

activate_environment() {
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  cd "$ROOT"
}

ensure_runtime_dir() { mkdir -p "$ROOT/.run"; }
backend_pid_file() { printf '%s/.run/backend.pid' "$ROOT"; }

# Returns success (0) when the port is occupied; failure (1) when available.
port_is_listening() {
  local host="$1" port="$2"
  python - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket
import sys
host, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket()
# Server-like semantics match uvicorn: without SO_REUSEADDR a TIME_WAIT
# socket on the same local port causes a false "occupied" result.
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind((host, port))
except OSError:
    raise SystemExit(0)
else:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

backend_healthy() {
  curl --connect-timeout 1 --max-time 3 -fsS "$HEALTH_URL" >/dev/null 2>&1
}

show_health() {
  curl --connect-timeout 2 --max-time 5 -fsS "$HEALTH_URL" || return 1
  printf '\n'
}

read_recorded_backend_pid() {
  local pid_file
  pid_file="$(backend_pid_file)"
  if [[ -f "$pid_file" ]]; then tr -d '[:space:]' < "$pid_file"; fi
}

is_pid_running() {
  local pid="${1:-}" state
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  if command -v ps >/dev/null 2>&1; then
    state="$(ps -p "$pid" -o stat= 2>/dev/null | tr -d '[:space:]' || true)"
    [[ -n "$state" && "$state" != Z* ]]
  else
    return 0
  fi
}

is_goldbot_backend_pid() {
  local pid="${1:-}" command_line
  is_pid_running "$pid" || return 1
  command -v ps >/dev/null 2>&1 || return 1
  command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$command_line" == *"uvicorn"* && "$command_line" == *"$ASGI_APP"* ]]
}

wait_for_backend() {
  local attempt
  for ((attempt = 1; attempt <= STARTUP_TIMEOUT; attempt++)); do
    backend_healthy && return 0
    sleep 1
  done
  return 1
}

stop_pid_gracefully() {
  local pid="${1:-}" description="${2:-process}" attempt
  [[ -n "$pid" ]] || return 0
  is_pid_running "$pid" || return 0

  log "Stopping ${description} (PID ${pid})..."
  kill -TERM "$pid" 2>/dev/null || true
  for ((attempt = 1; attempt <= 10; attempt++)); do
    is_pid_running "$pid" || return 0
    sleep 1
  done
  warn "${description} did not stop after 10 seconds; sending SIGKILL."
  kill -KILL "$pid" 2>/dev/null || true
}

check_python_backend() {
  log "Checking Python backend imports and application configuration..."
  (
    cd "$ROOT"
    source "$ROOT/.venv/bin/activate"
    export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
    ASGI_APP="$ASGI_APP" python - <<'PY'
import importlib
import os
module_name, app_name = os.environ["ASGI_APP"].split(":", 1)
module = importlib.import_module(module_name)
application = getattr(module, app_name)
print(f"Backend import OK: {module_name}:{app_name}")
print(f"ASGI application: {type(application).__name__}")
PY
  )
}

check_frontend_config() {
  log "Checking frontend package.json..."
  (
    cd "$ROOT/frontend"
    node - <<'NODE'
const fs = require("node:fs");
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
if (!pkg.scripts || !pkg.scripts.dev) {
  throw new Error('package.json must define a "dev" script.');
}
console.log(`Frontend package OK: ${pkg.name || "(unnamed)"}`);
console.log(`Development command: ${pkg.scripts.dev}`);
NODE
  )
}

run_checks() {
  require_command python
  require_command curl
  require_command node
  require_command npm
  check_project_layout
  activate_environment

  log "Project root: $ROOT"
  log "Checking Python syntax..."
  python -m compileall -q "$ROOT/src/goldbot"
  check_python_backend
  check_frontend_config

  if backend_healthy; then
    log "Backend health endpoint is responding:"
    show_health
  else
    log "Backend is not currently responding at $HEALTH_URL (this is OK during --check)."
  fi
  log "Configuration and project checks passed."
}

start_backend() {
  local pid_file existing_pid
  require_command python
  require_command curl
  check_project_layout
  activate_environment
  ensure_runtime_dir
  pid_file="$(backend_pid_file)"

  if backend_healthy; then
    log "Backend is already healthy at $HEALTH_URL."
    show_health || true
    return 0
  fi

  if port_is_listening "$BACKEND_HOST" "$BACKEND_PORT"; then
    die "Port ${BACKEND_HOST}:${BACKEND_PORT} is already occupied, but the GoldBot health endpoint is not responding. Check the process before starting another backend."
  fi

  existing_pid="$(read_recorded_backend_pid || true)"
  if is_pid_running "$existing_pid"; then
    if is_goldbot_backend_pid "$existing_pid"; then
      warn "A recorded GoldBot backend process (PID $existing_pid) exists but is not healthy."
      warn "Recent backend log output:"
      tail -n 40 "$BACKEND_LOG" 2>/dev/null || true
      die "Refusing to start a second backend. Inspect the existing process and log."
    fi
    warn "The recorded PID ($existing_pid) belongs to a different process. Removing the stale PID file without touching that process."
  fi
  rm -f "$pid_file"

  local -a uvicorn_args
  uvicorn_args=("$ASGI_APP" --host "$BACKEND_HOST" --port "$BACKEND_PORT")
  if [[ "$RELOAD" == "1" || "$RELOAD" == "true" || "$RELOAD" == "yes" ]]; then
    uvicorn_args+=(--reload)
  fi

  log "Starting backend API..."
  log "Command: python -m uvicorn ${uvicorn_args[*]}"
  log "Backend log: $BACKEND_LOG"
  nohup python -m uvicorn "${uvicorn_args[@]}" >>"$BACKEND_LOG" 2>&1 </dev/null &
  BACKEND_PID=$!
  printf '%s\n' "$BACKEND_PID" > "$pid_file"

  if wait_for_backend; then
    BACKEND_STARTED_BY_THIS_RUN=1
    log "Backend is healthy at http://${BACKEND_HOST}:${BACKEND_PORT}"
    show_health || true
    return 0
  fi

  warn "Backend failed to become healthy within ${STARTUP_TIMEOUT} seconds."
  tail -n 60 "$BACKEND_LOG" 2>/dev/null || true
  stop_pid_gracefully "$BACKEND_PID" "backend"
  rm -f "$pid_file"
  BACKEND_PID=""
  die "Backend startup failed. See $BACKEND_LOG for details."
}

start_backend_detached() {
  start_backend
  log "Backend is running in the background."
  log "PID file: $(backend_pid_file)"
  log "Log file: $BACKEND_LOG"
  log "Health: $HEALTH_URL"
}

status_report() {
  local pid
  check_project_layout
  log "Project root: $ROOT"
  if backend_healthy; then
    log "Backend: RUNNING ($HEALTH_URL)"
    show_health || true
  else
    log "Backend: NOT HEALTHY ($HEALTH_URL)"
  fi
  pid="$(read_recorded_backend_pid || true)"
  if is_goldbot_backend_pid "$pid"; then
    log "Recorded backend PID: $pid (GoldBot Uvicorn process)"
  elif is_pid_running "$pid"; then
    warn "Recorded PID $pid is running but does not look like the configured GoldBot Uvicorn process."
  else
    log "Recorded backend PID: not running / not recorded"
  fi
  if port_is_listening "$FRONTEND_HOST" "$FRONTEND_PORT"; then
    log "Frontend: port ${FRONTEND_HOST}:${FRONTEND_PORT} is occupied (likely running)."
    log "URL: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
  else
    log "Frontend: NOT RUNNING"
  fi
}

stop_backend() {
  local pid pid_file
  ensure_runtime_dir
  pid_file="$(backend_pid_file)"
  pid="$(read_recorded_backend_pid || true)"

  if [[ -z "$pid" ]]; then
    if backend_healthy; then
      warn "The API is responding, but this script has no PID record for it."
      warn "It was probably started manually. Stop it using the terminal/process manager that started it."
      return 0
    fi
    log "No recorded GoldBot backend process is running."
    return 0
  fi

  if ! is_pid_running "$pid"; then
    rm -f "$pid_file"
    log "Removed stale backend PID file."
    return 0
  fi

  if ! is_goldbot_backend_pid "$pid"; then
    die "PID $pid is running but does not match the configured GoldBot backend. Refusing to stop an unrelated process; inspect $pid_file manually."
  fi

  stop_pid_gracefully "$pid" "GoldBot backend"
  rm -f "$pid_file"
  log "Backend stopped."
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if (( FRONTEND_STARTED_BY_THIS_RUN )) && [[ -n "$FRONTEND_PID" ]]; then
    if command -v setsid >/dev/null 2>&1; then
      kill -TERM -- "-$FRONTEND_PID" 2>/dev/null || true
    else
      kill -TERM "$FRONTEND_PID" 2>/dev/null || true
      pkill -TERM -P "$FRONTEND_PID" 2>/dev/null || true
    fi
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi

  if (( BACKEND_STARTED_BY_THIS_RUN )) && [[ -n "$BACKEND_PID" ]]; then
    stop_pid_gracefully "$BACKEND_PID" "GoldBot backend"
    local recorded
    recorded="$(read_recorded_backend_pid || true)"
    [[ "$recorded" == "$BACKEND_PID" ]] && rm -f "$(backend_pid_file)"
  fi

  exit "$exit_code"
}

start_full_system() {
  require_command npm
  require_command node
  require_command curl
  check_project_layout
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  start_backend

  cd "$ROOT/frontend"
  if [[ ! -d node_modules ]]; then
    log "Frontend dependencies are not installed. Running npm install..."
    npm install
  else
    log "Frontend node_modules already exists; skipping npm install."
  fi

  log "Starting React frontend..."
  log "Dashboard: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
  log "Press Ctrl+C to stop the frontend and the backend started by this script."

  if command -v setsid >/dev/null 2>&1; then
    setsid npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort &
  else
    npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort &
  fi
  FRONTEND_PID=$!
  FRONTEND_STARTED_BY_THIS_RUN=1
  wait "$FRONTEND_PID"
}

resolve_root
case "$MODE" in
  check)   run_checks ;;
  backend) start_backend_detached ;;
  status)  status_report ;;
  stop)    stop_backend ;;
  full)    start_full_system ;;
  *)       usage; die "Unsupported mode: $MODE" ;;
esac
