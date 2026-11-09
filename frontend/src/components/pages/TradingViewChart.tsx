import React, { useEffect, useRef, useState } from "react"

// Official TradingView embeddable Advanced Chart widget (free, supported
// embedding method — no scraping, no private endpoints). TradingView is the
// charting/visual-reference layer only: GoldBot's analysis engine never
// consumes TradingView data.
//
// Docs: https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/

const DEFAULT_SYMBOL = "OANDA:XAUUSD"

const TIMEFRAMES: Array<[string, string, string]> = [
  // [label, interval, seconds]
  ["1m", "1", "60"],
  ["5m", "5", "300"],
  ["15m", "15", "900"],
  ["30m", "30", "1800"],
  ["1h", "60", "3600"],
  ["4h", "240", "14400"],
  ["1D", "D", "86400"],
  ["1W", "W", "604800"],
]

interface Props {
  symbol?: string
}

const TradingViewChart: React.FC<Props> = ({ symbol = DEFAULT_SYMBOL }) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [interval, setIntervalStr] = useState("15")
  const [fullscreen, setFullscreen] = useState(false)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    const host = containerRef.current
    if (!host) return
    host.innerHTML = ""
    setLoadError(false)

    const widgetDiv = document.createElement("div")
    widgetDiv.className = "tradingview-widget-container__widget"
    widgetDiv.style.height = "100%"
    widgetDiv.style.width = "100%"
    host.appendChild(widgetDiv)

    const script = document.createElement("script")
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
    script.type = "text/javascript"
    script.async = true
    script.onerror = () => setLoadError(true)
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval,
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      enable_publishing: false,
      backgroundColor: "rgba(26, 26, 36, 1)",
      gridColor: "rgba(38, 38, 47, 1)",
      hide_side_toolbar: false,
      allow_symbol_change: true,
      details: false,
      withdateranges: true,
      save_image: false,
    })
    host.appendChild(script)

    const timeout = window.setTimeout(() => {
      if (host.querySelector("iframe") === null) setLoadError(true)
    }, 8000)

    return () => {
      window.clearTimeout(timeout)
      host.innerHTML = ""
    }
  }, [symbol, interval])

  const heightClass = fullscreen ? "tv-fullscreen" : "tv-normal"

  return (
    <section className="page">
      <header className="page-head">
        <h2>TradingView chart</h2>
        <div className="tv-controls">
          <select
            value={interval}
            onChange={(e) => setIntervalStr(e.target.value)}
            aria-label="Chart timeframe"
          >
            {TIMEFRAMES.map(([label, value]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button className="tv-fs-btn" onClick={() => setFullscreen((f) => !f)}>
            {fullscreen ? "Exit fullscreen" : "Fullscreen"}
          </button>
        </div>
      </header>
      <p className="muted">
        Official TradingView embed (display only — GoldBot's analysis engine uses
        its own market-data pipeline). Default instrument:{" "}
        <code>{DEFAULT_SYMBOL}</code>.
      </p>
      <div className={`tv-chart ${heightClass}`}>
        <div
          ref={containerRef}
          className="tradingview-widget-container"
          style={{ height: "100%", width: "100%" }}
        />
        {loadError && (
          <div className="tv-fallback">
            TradingView widget could not load (no network access or blocked
            script). GoldBot's own chart on the “Live market” page keeps
            working offline.
          </div>
        )}
      </div>
    </section>
  )
}

export default TradingViewChart
