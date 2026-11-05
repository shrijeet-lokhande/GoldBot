import React, { useState } from "react"
import "./index.css"
import Overview from "./components/pages/Overview"
import LiveMarket from "./components/pages/LiveMarket"
import TradeApproval from "./components/pages/TradeApproval"
import OpenPositions from "./components/pages/OpenPositions"
import TradeHistory from "./components/pages/TradeHistory"
import PerformanceAnalytics from "./components/pages/PerformanceAnalytics"
import BotConfiguration from "./components/pages/BotConfiguration"
import SystemHealth from "./components/pages/SystemHealth"
import { useEngineState } from "./lib/useEngineState"

type PageName =
  | "overview"
  | "live"
  | "approval"
  | "positions"
  | "history"
  | "performance"
  | "config"
  | "health"

const NAV: Array<[PageName, string]> = [
  ["overview", "Overview"],
  ["live", "Live market"],
  ["approval", "Trade approval"],
  ["positions", "Open positions"],
  ["history", "Trade history"],
  ["performance", "Performance"],
  ["config", "Configuration"],
  ["health", "System health"],
]

const App: React.FC = () => {
  const [page, setPage] = useState<PageName>("overview")
  const engineState = useEngineState()

  const pendingCount = engineState.proposals.filter(
    (p) => p.status === "pending"
  ).length

  return (
    <div className="app">
      <nav>
        <div className="brand">
          GoldBot
          <small>paper · XAUUSD · 15m</small>
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
        {page === "approval" && <TradeApproval state={engineState} />}
        {page === "positions" && <OpenPositions state={engineState} />}
        {page === "history" && <TradeHistory />}
        {page === "performance" && <PerformanceAnalytics />}
        {page === "config" && <BotConfiguration />}
        {page === "health" && <SystemHealth state={engineState} />}
      </main>
    </div>
  )
}

export default App
