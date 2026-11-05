import React, { useState } from "react"
import { Position, apiPost, fmt, fmtMoney } from "../../lib/api"
import { EngineState } from "../../lib/useEngineState"

const OpenPositions: React.FC<{ state: EngineState }> = ({ state }) => {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const closeAll = async (symbol?: string) => {
    setBusy(true)
    setMessage(null)
    try {
      const result = await apiPost<any>("/api/v1/positions/close", { symbol })
      setMessage(`Closed ${result.symbol ?? ""}: P&L ${fmtMoney(result.pnl ?? 0)}`)
    } catch (e: any) {
      setMessage(e?.message ?? "Close failed")
    } finally {
      setBusy(false)
    }
  }

  const positions: Position[] = state.positions

  return (
    <div className="page">
      <h1>Open positions</h1>
      <div className="card">
        {positions.length === 0 ? (
          <p>No open positions. When the engine enters a trade, it appears here with live P&L.</p>
        ) : (
          <table className="simple">
            <thead>
              <tr>
                <th>Symbol</th><th>Direction</th><th>Volume</th><th>Entry</th>
                <th>Current</th><th>Stop</th><th>Target</th><th>Unrealised</th><th></th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos: Position, i: number) => (
                <tr key={i}>
                  <td>{pos.symbol}</td>
                  <td className={pos.direction === "LONG" ? "positive" : "negative"}>
                    {pos.direction}
                  </td>
                  <td>{fmt(pos.volume, 2)}</td>
                  <td>{fmt(pos.entry_price)}</td>
                  <td>{fmt(pos.current_price)}</td>
                  <td>{pos.stop_loss ? fmt(pos.stop_loss) : "—"}</td>
                  <td>{pos.take_profit ? fmt(pos.take_profit) : "—"}</td>
                  <td className={pos.unrealised_pnl >= 0 ? "positive" : "negative"}>
                    {fmtMoney(pos.unrealised_pnl)}
                  </td>
                  <td>
                    <button
                      className="btn secondary"
                      disabled={busy}
                      onClick={() => void closeAll(pos.symbol)}
                    >
                      Close
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {message && <div className="card"><p>{message}</p></div>}
    </div>
  )
}

export default OpenPositions
