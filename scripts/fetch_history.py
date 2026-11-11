#!/usr/bin/env python3
"""Data-acquisition pipeline for XAUUSD history.

Fetches historical XAUUSD candles from OANDA v20 (practice environment by
default) and appends them to data/raw/xauusd_{timeframe}.csv in the same
normalized format as the existing fixture.

Without credentials the script still works as a status/check tool: it
reports current data coverage and states the limitation (today only
1,510 x 15m bars, ~15.7 days, are available — far too little for robust
walk-forward validation).

Usage:
    uv run python scripts/fetch_history.py --status
    uv run python scripts/fetch_history.py --timeframe 15m --years 2 \
        [--granularity M15]

Credentials (never commit): GOLD_OANDA_API_TOKEN, optionally
GOLD_OANDA_ACCOUNT_ID and GOLD_OANDA_ENV (practice|live; live is blocked
from this script).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

RAW_DIR = PROJECT_ROOT / "data" / "raw"
CANONICAL = "XAUUSD"
OANDA_INSTRUMENT = "XAU_USD"
GRANULARITY_BY_TF = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "1d": "D"}
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "D": 1440}


def data_status() -> int:
    fixture = PROJECT_ROOT / "data" / "fixtures" / "sample_xauusd_15m.csv"
    print("== GoldBot data coverage ==")
    if RAW_DIR.exists():
        for f in sorted(RAW_DIR.glob("*.csv")):
            lines = sum(1 for _ in f.open())
            print(f"  raw: {f.name}: {lines} rows")
    else:
        print("  raw: no files yet")
    if fixture.exists():
        lines = sum(1 for _ in fixture.open()) - 1
        print(f"  fixture: sample_xauusd_15m.csv: {lines} bars")
        print(
            "  LIMITATION: ~15.7 days of 15m bars. This is enough to build and\n"
            "  smoke-test the pipeline, NOT enough for robust walk-forward\n"
            "  validation of a directional model. Run with credentials to extend."
        )
    else:
        print("  fixture: missing")
    if not os.environ.get("GOLD_OANDA_API_TOKEN"):
        print(
            "  credentials: GOLD_OANDA_API_TOKEN not set — fetch mode unavailable\n"
            "  (set it in .env, never commit the value)"
        )
        return 1
    print("  credentials: OANDA token present — fetch mode available")
    return 0


def _oanda_request(path: str, params: dict) -> dict:
    import json
    import urllib.parse
    import urllib.request

    token = os.environ["GOLD_OANDA_API_TOKEN"]
    env = os.environ.get("GOLD_OANDA_ENV", "practice")
    if env not in ("practice",):
        print("refusing: fetch_history only runs against the practice host", file=sys.stderr)
        sys.exit(2)
    host = "https://api-fxpractice.oanda.com"
    url = host + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "UNIX"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _granularity(timeframe: str) -> str:
    g = GRANULARITY_BY_TF.get(timeframe)
    if not g:
        raise SystemExit(f"unsupported timeframe {timeframe!r}; use {sorted(GRANULARITY_BY_TF)}")
    return g


def fetch_history(timeframe: str, years: float) -> int:
    gran = _granularity(timeframe)
    out_path = RAW_DIR / f"xauusd_{timeframe}.csv"
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    minutes = TF_MINUTES[gran]
    max_span = timedelta(minutes=minutes * 5000)  # OANDA hard count cap
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(years * 365))

    header = "timestamp,open,high,low,close,volume\n"
    if not out_path.exists():
        out_path.write_text(header)

    cursor = start
    added = 0
    with out_path.open("a") as fh:
        while cursor < end:
            span_end = min(cursor + max_span, end)
            params = {
                "granularity": gran,
                "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": span_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "price": "M",
                "count": "5000",
            }
            payload = _oanda_request(
                f"/v3/instruments/{OANDA_INSTRUMENT}/candles", params
            )
            candles = payload.get("candles", [])
            for c in candles:
                if not c.get("complete"):
                    continue
                mid = c["mid"]
                ts = datetime.fromtimestamp(
                    float(c["time"]), tz=timezone.utc
                ).isoformat()
                vol = c.get("volume", 0)
                fh.write(
                    f"{ts},{mid['o']},{mid['h']},{mid['l']},{mid['c']},{vol}\n"
                )
                added += 1
            if not candles:
                break
            last_ts = datetime.fromtimestamp(float(candles[-1]["time"]), tz=timezone.utc)
            cursor = last_ts + timedelta(minutes=minutes)
            print(f"  ... {added} bars so far (at {last_ts:%Y-%m-%d %H:%M} UTC)")

    print(f"done: appended {added} bars to {out_path.relative_to(PROJECT_ROOT)}")
    print("provenance: source=OANDA v20 practice REST, instrument=XAU_USD, "
          "price=M (mid); tick volume is NOT exchange volume.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="report data coverage")
    parser.add_argument("--timeframe", default="15m", help="15m|1m|5m|1h|1d")
    parser.add_argument("--years", type=float, default=2.0, help="years of history to fetch")
    args = parser.parse_args()

    if args.status or not os.environ.get("GOLD_OANDA_API_TOKEN"):
        return data_status()
    return fetch_history(args.timeframe, args.years)


if __name__ == "__main__":
    sys.exit(main())
