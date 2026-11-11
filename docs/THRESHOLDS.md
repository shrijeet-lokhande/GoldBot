# GoldBot Threshold & Parameter Rationale

Every numeric threshold used by detection rules is documented here with its
rationale. Nothing is arbitrary: constants are either (a) observed price
extremes, (b) industry-standard indicator defaults, or (c) tolerance factors
expressed in ATR (volatility-scaled so they adapt to gold's regime).

## Indicator periods (industry-standard defaults)

| Parameter | Default | Rationale |
|---|---|---|
| EMA fast / trend / long | 20 / 50 / 200 | Conventional MA stack; 200 is the widely watched long trend line on gold charts. |
| RSI period | 14 | Wilder's original default; standard on every gold chart. |
| MACD | 12 / 26 / 9 | Appel's original standard. |
| Stoch RSI | 14 / 14 / 3 / 3 | Standard stochastic-of-RSI defaults. |
| Bollinger | 20, 2.0σ | Bollinger's standard band definition. |
| ATR / ADX | 14 | Wilder's defaults. |
| SMA | 20 | Matches the BB middle band for coherent readings. |
| Fib ratios | .236/.382/.5/.618/.786, ext 1.0–2.618 | Fixed mathematical ratios of the measured swing. |

All periods are configurable in `config/settings.yaml` where relevant; the
analysis engine uses the same defaults so strategy and analysis agree.

## Market-structure tolerances (ATR-scaled)

ATR scaling makes each tolerance regime-aware: in a high-volatility gold
tape a fixed point-distance would over-cluster or miss entirely.

| Constant | Value | Rule | Rationale |
|---|---|---|---|
| Swing pivot window | 3 left / 3 right bars | fractal high/low | Minimum symmetric window that suppresses single-bar noise while keeping pivots responsive on 15m gold data. |
| Liquidity sweep | wick > 0.05 ATR beyond level, close back inside | sweep detection | Requires a *meaningful* penetration; 0.05 ATR filters micro-wicks that never touched resting liquidity, while the close-back-inside condition distinguishes sweeps from genuine breaks. |
| Equal highs/lows | within 0.15 ATR | ≥2 swing points | Liquidity pools form where stops sit at effectively the same price; 0.15 ATR is tight enough to keep the pool honest but tolerant of broker-level tick noise. |
| Order block | next-bar body > 1.0 ATR after an opposing candle | OB detection | One full ATR of body is a displacement in any gold regime; smaller moves are drift, not institutional order flow. |
| FVG | 3-candle gap (low[i] > high[i-2], mirrored) | imbalance | Standard ICT fair-value-gap definition; filled gaps are excluded from the active set. |
| Consolidation | ≥5-bar window, total range < 2.0 ATR | range detection | Five bars is the shortest span traders call a "range" on M15; 2 ATR bounds the noise envelope of a true consolidation. |
| Breakout confirmation | close outside range within 5 bars; false = close back inside within 2 bars | breakout/false | A *close* (not a wick) confirms intent; 2 bars is enough to catch stop-run reversals without flagging every retest. |
| Rejection zone | wick ≥ 60% of bar range beyond the body | rejection | A wick that spans most of the bar shows one-sided rejection; 60% requires the rejection to dominate the candle. |
| BOS/CHOCH | close beyond most recent confirmed opposite-fractal level | structure event | Close-based (not wick-based) to avoid stop-hunt mislabels; CHOCH is a break against the prevailing trend vote. |
| Trend vote | last high label + last low label | trend state | HH+HL = up; LH+LL = down; mixed = range. Strict sequence semantics, no majority fitting. |

## Session windows (UTC)

| Session | Window (UTC) | Rationale |
|---|---|---|
| Asia | 00:00–07:00 | Tokyo/Hong Kong liquidity; gold ranges thin, Asia H/L is the classic London sweep target. |
| London | 07:00–12:00 | LBMA/CFD liquidity window; sets intraday direction ~most days. |
| New York | 12:00–20:00 | US data at 12:30/13:30/14:00 UTC; London-NY overlap (12:00–16:00) is the deepest window; gold CFD liquidity thins after 20:00 UTC. |

Boundaries are fixed UTC hours (see `analysis/session_levels.py`). Level
values themselves are observed extremes (PDH/PDL/PWH/PWL, session H/L) — no
numeric fitting involved.

## Live risk safeguards (server-side defaults)

| Guard | Default | Rationale |
|---|---|---|
| max_risk_per_trade_pct | 0.5% | Half of the classic 1% rule for an unattended system. |
| max_daily_loss_pct | 2.0% | One bad day cannot exceed ~4 losing trades at the per-trade cap. |
| max_open_positions | 2 | Bounds correlated exposure in a single instrument. |
| max_account_exposure_pct | 300% | ≈3:1 notional/equity; deliberate margin for gold CFD leverage while capping catastrophic liquidation risk. |
| max_order_volume_lots | 5.0 | 500 oz ≈ $1.2M notional ceiling at $2400/oz. |
| max_leverage | 20 | Above typical retail gold leverage offers; checked against broker specs. |
| min_risk_reward_ratio | 1.5 | Expectancy survives a 40% win rate at 1.5R. |
| max_atr_pct_of_price | 0.75% | Gold's 15m ATR is ~0.1–0.3% normally; >0.75% signals event-shock tape where stops get gapped. |
| max_spread | 0.5 (USD) | Typical XAUUSD raw spread is 0.1–0.3; 0.5 is an illiquid-tape cutoff. |
| max_data_age_seconds | 30 | A gold quote older than 30s during open hours is unreliable for live execution. |
| Session restriction | 07:00–20:59 UTC Mon–Fri | Avoids the thin Asian hours and the weekend gap window. |

## Analysis engine scoring

| Constant | Value | Rationale |
|---|---|---|
| Minimum bars for analysis | 30 | Two days of M15 data; below this the structure engine's pivot windows cannot form. |
| Minimum bars per timeframe vote | 25 | EMA-20/50 warm-up floor; below it a vote would be noise. |
| ADX trending / weak | ≥25 / <20 | The conventional 25 trend / 20 range boundaries. |
| BB bandwidth "elevated" | >6% | Gold's 20-bar bandwidth is usually 0.3–3%; >6% is an extreme-volatility expansion. |
| Bias weights | 1w/d:4, 4h:3, 1h:2, ≤30m:1 | Higher timeframes dominate directional bias; equal votes tie → neutral. |
| Confidence adjustments | ±20 aligned TFs, ±10 ADX, +5 structure event, −5 no fundamentals | Transparent heuristics bounded to 5–90; explicitly NOT calibrated probabilities. |

## Data quality

| Constant | Value | Rationale |
|---|---|---|
| stale_data_seconds (config) | 120 | Paper replay tolerance; live quotes use the 30s live guard above. |
| Volume reliability | any positive volume | Tick-volume proxies are accepted for VWAP only with an explicit "not centralized exchange volume" caveat; zero-volume feeds mark VWAP unavailable. |
