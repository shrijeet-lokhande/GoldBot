import React from "react"
import { Position, Proposal, fmt, fmtMoney } from "../../lib/api"
import { EngineState } from "../../lib/useEngineState"

const Overview: React.FC<{ state: EngineState }> = ({ state }) => {
  const { quote, account, positions, proposals, health, connected } = state

  const pending = proposals.filter((p: Proposal) => p.status === "pending")

  return (
    <div className="page">
      <h1>Overview</h1>

      <div className="card">
        <h2>Market</h2>
        <div className="grid">
          <div className="stat-line">Mid price<b>{quote ? fmt(quote.mid_price) : "—"}</b></div>
          <div className="stat-line">Bid<b className="muted">{quote ? fmt(quote.bid) : "—"}</b></div>
          <div className="stat-line">Ask<b className="muted">{quote ? fmt(quote.ask) : "—"}</b></div>
          <div className="stat-line">Spread<b>{quote ? fmt(quote.spread) : "—"}</b></div>
          <div className="stat-line">Instrument<b>{health?.instrument_symbol ?? "—"}</b></div>
          <div className="stat-line">Connection<b className={connected ? "positive" : "negative"}>
            {connected ? "LIVE" : "polling"}
          </b></div>
        </div>
      </div>

      <div className="card">
        <h2>Account</h2>
        <div className="grid">
          <div className="stat-line">Equity<b>{account ? fmtMoney(account.equity) : "—"}</b></div>
          <div className="stat-line">Balance<b>{account ? fmtMoney(account.balance) : "—"}</b></div>
          <div className="stat-line">Unrealised P&L<b
            className={account && account.unrealised_pnl >= 0 ? "positive" : "negative"}>
            {account ? fmtMoney(account.unrealised_pnl) : "—"}</b></div>
          <div className="stat-line">Realised P&L<b
            className={account && account.realised_pnl >= 0 ? "positive" : "negative"}>
            {account ? fmtMoney(account.realised_pnl) : "—"}</b></div>
        </div>
      </div>

      <div className="card">
        <h2>Open positions</h2>
        {positions.length === 0 ? (
          <p>No open positions.</p>
        ) : (
          <table className="simple">
            <thead>
              <tr><th>Symbol</th><th>Side</th><th>Volume</th><th>Entry</th><th>Current</th><th>P&L</th></tr>
            </thead>
            <tbody>
              {positions.map((pos: Position, i: number) => (
                <tr key={i}>
                  <td>{pos.symbol}</td>
                  <td className={pos.direction === "LONG" ? "positive" : "negative"}>{pos.direction}</td>
                  <td>{pos.volume}</td>
                  <td>{fmt(pos.entry_price)}</td>
                  <td>{fmt(pos.current_price)}</td>
                  <td className={pos.unrealised_pnl >= 0 ? "positive" : "negative"}>
                    {fmtMoney(pos.unrealised_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Pending trade proposals ({pending.length})</h2>
        {pending.length === 0 ? (
          <p>No pending proposals. Approve them from the Trade Approval page.</p>
        ) : (
          pending.slice(0, 5).map((p: Proposal) => (
            <div key={p.proposal_id} className="proposal-row">
              <span className={p.direction === "long" ? "positive" : "negative"}>
                {p.direction.toUpperCase()}
              </span>
              <div className="meta">
                entry {fmt(p.entry_price)} · SL {fmt(p.stop_loss)} · TP {fmt(p.take_profit)}
                <br />
                <span className="reason">{p.decision_reason}</span>
              </div>
              <span className="badge pending">pending</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default Overview
