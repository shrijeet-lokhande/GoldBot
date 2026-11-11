#!/usr/bin/env bash
#
# GoldBot — graceful shutdown of services started by start.sh/start_goldbot.sh.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$ROOT/start_goldbot.sh" --root "$ROOT" --stop
