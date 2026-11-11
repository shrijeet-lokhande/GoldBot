import React, { useEffect, useRef } from "react"
import {
  createChart,
  ColorType,
  IChartApi,
  ISeriesApi,
  LineSeriesPartialOptions,
} from "lightweight-charts"
import { CandleBar } from "../../lib/api"
import { EngineState } from "../../lib/useEngineState"

interface Props {
  state: EngineState
}

const LiveMarket: React.FC<Props> = ({ state }) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null)
  const lineRefs = useRef<Record<string, ISeriesApi<"Line">>>({})

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#1a1a24" },
        textColor: "#6b6b80",
      },
      grid: { vertLines: { color: "#26262f" }, horzLines: { color: "#26262f" } },
      rightPriceScale: { borderColor: "#333344" },
      timeScale: { borderColor: "#333344", timeVisible: true },
      autoSize: true,
    })
    candleRef.current = chart.addCandlestickSeries({
      upColor: "#4caf50",
      downColor: "#f44336",
      wickUpColor: "#4caf50",
      wickDownColor: "#f44336",
      borderVisible: false,
    })
    const seriesDefs: Array<[string, LineSeriesPartialOptions]> = [
      ["ema_fast", { color: "#2196f3", lineWidth: 1 }],
      ["ema_trend", { color: "#ffb300", lineWidth: 1 }],
      ["ema_long", { color: "#9c27b0", lineWidth: 1 }],
    ]
    for (const [name, opts] of seriesDefs) {
      lineRefs.current[name] = chart.addLineSeries(opts)
    }
    chartRef.current = chart
    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      lineRefs.current = {}
    }
  }, [])

  useEffect(() => {
    const candleSeries = candleRef.current
    if (!candleSeries) return
    candleSeries.setData(state.candles as any)
    const series = state.indicators.series ?? {}
    for (const [name, api] of Object.entries(lineRefs.current)) {
      const points = (series[name] ?? []) as number[]
      api.setData(
        state.candles
          .map((c: CandleBar, i: number) => ({
            time: c.time,
            value: points[i],
          }))
          .filter((p) => typeof p.value === "number" && !Number.isNaN(p.value)) as any,
      )
    }
  }, [state.candles, state.indicators])

  // Live tick: shift the current bar as price changes between closes.
  useEffect(() => {
    const candleSeries = candleRef.current
    if (!candleSeries || !state.quote || state.candles.length === 0) return
    const last = state.candles[state.candles.length - 1]
    try {
      candleSeries.update({
        time: last.time,
        open: last.open,
        high: Math.max(last.high, state.quote.mid_price),
        low: Math.min(last.low, state.quote.mid_price),
        close: state.quote.mid_price,
      } as any)
    } catch {
      /* bad tick, ignore */
    }
  }, [state.quote])

  return (
    <div className="page">
      <h1>Live market</h1>
      <div className="card">
        <div className="toolbar">
          <span className="muted">
            Symbol: <b>{state.health?.instrument_symbol ?? "—"}</b>
          </span>
          <span className="muted">
            Timeframe: 15m
          </span>
          <span className="muted">
            Bars: {state.candles.length}
            {state.health ? ` / ${state.health.total_bars}` : ""}
          </span>
          <span className="muted">
            Source: <b>{state.quote?.source ?? "engine_replay(paper)"}</b>
            {state.quote?.as_of_utc ? ` · as of ${state.quote.as_of_utc}` : ""}
          </span>
        </div>
        <div ref={containerRef} className="chart-container" />
      </div>
      <p className="muted">Chart data streams from the engine replay via WebSocket.</p>
    </div>
  )
}

export default LiveMarket
