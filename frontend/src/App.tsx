import React, { useEffect, useState } from "react"
import "./index.css"
import Overview from "./components/pages/Overview"
import LiveMarket from "./components/pages/LiveMarket"
import TradeApproval from "./components/pages/TradeApproval"
import OpenPositions from "./components/pages/OpenPositions"
import TradeHistory from "./components/pages/TradeHistory"
import PerformanceAnalytics from "./components/pages/PerformanceAnalytics"
import BotConfiguration from "./components/pages/BotConfiguration"
import SystemHealth from "./components/pages/SystemHealth"
import TradingViewChart from "./components/pages/TradingViewChart"
import AccountConnections from "./components/pages/AccountConnections"
import { useEngineState } from "./lib/useEngineState"
import { fetchInstrument } from "./lib/api"

type PageName =
  | "overview"
  | "live"
  | "tradingview"
  | "approval"
  | "positions"
  | "history"
  | "performance"
  | "config"
  | "connections"
  | "health"

const NAV: Array<[PageName, string]> = [
  ["overview", "Overview"],
  ["live", "Live market"],
  ["tradingview", "TradingView"],
  ["approval", "Trade approval"],
  ["positions", "Open positions"],
  ["history", "Trade history"],
  ["performance", "Performance"],
  ["config", "Configuration"],
  ["connections", "Mode & accounts"],
  ["health", "System health"],
]

const App: React.FC = () => {
  const [page, setPage] = useState<PageName>("overview")
  const engineState = useEngineState()
  const [instrumentLabel, setInstrumentLabel] = useState<string | null>(null)

  useEffect(() => {
    void fetchInstrument()
      .then((i) => setInstrumentLabel(i.symbol))
      .catch(() => setInstrumentLabel(null))
  }, [])

  // Active execution mode is displayed at all times; paper is the default
  // and the live state is only shown when the backend reports it.
  const modeBadgeText =
    engineState.health?.mode === "live" ? "● LIVE" : "● PAPER"
  const modeBadgeClass =
    engineState.health?.mode === "live" ? "live" : "paper"

  const pendingCount = engineState.proposals.filter(
    (p) => p.status === "pending"
  ).length

  return (
    <div className="app">
      <nav>
        <div className="brand">
          GoldBot
          <small>paper · {instrumentLabel ?? "XAUUSD"} · {engineState.health?.instrument_symbol ?? "…"}</small>
        </div>
        {NAV.map(([key, label]) => (
          <button
            key={key}
            className={`nav-item ${page === key ? "active" : ""}`}
            onClick={() => setPage(key)}
          >
            {label}
            {key === "approval" && pendingCount > 0 ? ` (${pendingCount})` : ""}
          </button>
        ))}
        <div className="spacer" />
        <span className={`mode-badge ${modeBadgeClass}`}>{modeBadgeText}</span>
        <div className="conn">
          {engineState.connected ? "● websocket live" : "○ offline (polling)"}
        </div>
      </nav>

      <main>
        <p className="mobile-warning">
          The dashboard is optimised for a desktop browser window.
        </p>
        {page === "overview" && <Overview state={engineState} />}
        {page === "live" && <LiveMarket state={engineState} />}
        {page === "tradingview" && <TradingViewChart />}
        {page === "approval" && <TradeApproval state={engineState} />}
        {page === "positions" && <OpenPositions state={engineState} />}
        {page === "history" && <TradeHistory />}
        {page === "performance" && <PerformanceAnalytics />}
        {page === "config" && <BotConfiguration />}
        {page === "connections" && <AccountConnections />}
        {page === "health" && <SystemHealth state={engineState} />}
      </main>
    </div>
  )
}

export default App
