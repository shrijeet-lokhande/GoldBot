import React, { useEffect, useState } from "react"
import { Trade, apiGet, fmt, fmtMoney, ts } from "../../lib/api"

const TradeHistory: React.FC = () => {
  const [trades, setTrades] = useState<Trade[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await apiGet<Trade[]>("/api/v1/trades?limit=100")
        if (!cancelled) setTrades(data)
      } catch (e: any) {
        if (!cancelled) setError(e?.message)
      }
    }
    void load()
    const interval = setInterval(load, 3000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <div className="page">
      <h1>Trade history</h1>
      {error && <div className="card"><p className="negative">{error}</p></div>}
      <div className="card">
        {trades.length === 0 ? (
          <p>No closed trades yet.</p>
        ) : (
          <table className="simple">
            <thead>
              <tr>
                <th>Closed</th><th>Symbol</th><th>Side</th><th>Volume</th>
                <th>Entry</th><th>Close</th><th>Reason</th><th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t: Trade) => (
                <tr key={t.trade_id}>
                  <td>{ts(t.close_time)}</td>
                  <td>{t.symbol}</td>
                  <td className={t.side === "buy" ? "positive" : "negative"}>
                    {t.side.toUpperCase()}
                  </td>
                  <td>{fmt(t.volume, 2)}</td>
                  <td>{fmt(t.entry_price)}</td>
                  <td>{fmt(t.close_price)}</td>
                  <td className="muted">{t.reason}</td>
                  <td className={t.pnl >= 0 ? "positive" : "negative"}>
                    {fmtMoney(t.pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default TradeHistory
