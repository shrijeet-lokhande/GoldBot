import React, { useEffect, useState } from "react"
import { Perf, apiGet, fmt, fmtMoney } from "../../lib/api"

const PerformanceAnalytics: React.FC = () => {
  const [perf, setPerf] = useState<Perf | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await apiGet<Perf>("/api/v1/performance")
        if (!cancelled) setPerf(data)
      } catch (e: any) {
        if (!cancelled) setError(e?.message)
      }
    }
    void load()
    const interval = setInterval(load, 2500)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <div className="page">
      <h1>Performance</h1>
      {error && <div className="card"><p className="negative">{error}</p></div>}
      <div className="card">
        <h2>Summary</h2>
        {!perf ? (
          <p>Loading…</p>
        ) : (
          <div className="grid">
            <div className="stat-line">Total trades<b>{perf.total_trades}</b></div>
            <div className="stat-line">Win rate<b>{fmt(perf.win_rate, 1)}%</b></div>
            <div className="stat-line">Profit factor<b>{perf.profit_factor === null ? "—" : fmt(perf.profit_factor, 2)}</b></div>
            <div className="stat-line">Total P&L<b className={perf.total_pnl >= 0 ? "positive" : "negative"}>{fmtMoney(perf.total_pnl)}</b></div>
            <div className="stat-line">Average win<b className="positive">{fmtMoney(perf.average_win)}</b></div>
            <div className="stat-line">Average loss<b className="negative">{fmtMoney(perf.average_loss)}</b></div>
            <div className="stat-line">Max drawdown<b className="negative">{fmt(perf.max_drawdown_pct, 2)}%</b></div>
            <div className="stat-line">Equity<b>{fmtMoney(perf.current_equity)}</b></div>
          </div>
        )}
      </div>
      <p className="muted">
        Metrics come from the realised trade ledger of the running paper-broker session
        (spread and slippage simulated).
      </p>
    </div>
  )
}

export default PerformanceAnalytics
