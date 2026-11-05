import React, { useState } from "react"
import { Proposal, apiPost, fmt, ts } from "../../lib/api"
import { EngineState } from "../../lib/useEngineState"

const TradeApproval: React.FC<{ state: EngineState }> = ({ state }) => {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refreshAll = async () => {
    // Reflect the decision locally: refresh the full list from the server
    try {
      const fresh = await (await fetch("/api/v1/proposals")).json()
      state.proposals.splice(0, state.proposals.length, ...fresh)
    } catch {
      /* state will refresh via WS anyway */
    }
  }

  const decide = async (proposal: Proposal, approve: boolean) => {
    setBusy(proposal.proposal_id)
    setError(null)
    setNotice(null)
    try {
      const path = approve
        ? `/api/v1/proposals/${proposal.proposal_id}/approve`
        : `/api/v1/proposals/${proposal.proposal_id}/reject`
      const result = await apiPost<any>(path, { reason: "operator" })
      const reasons: Record<string, string> = {
        order_submitted: "Order submitted to the broker.",
        rejected_by_risk: `Risk engine rejected: ${result.reason ?? "see reason"}`,
        already_executed: "This proposal was already executed.",
      }
      setNotice(reasons[result.status] ?? `Decision recorded: ${result.status}`)
    } catch (e: any) {
      setError(e?.message ?? "Request failed")
    } finally {
      setBusy(null)
      void refreshAll()
    }
  }

  const pending = state.proposals.filter((p: Proposal) => p.status === "pending")
  const decided = state.proposals
    .filter((p: Proposal) => p.status !== "pending")
    .slice(-12)
    .reverse()

  return (
    <div className="page">
      <h1>Trade approval</h1>

      {error && <div className="card"><p className="negative">{error}</p></div>}
      {notice && <div className="card"><p className="positive">{notice}</p></div>}

      <div className="card">
        <h2>Pending orders ({pending.length})</h2>
        {pending.length === 0 ? (
          <p>No trade proposals awaiting approval. The engine will push proposals as signals fire.</p>
        ) : (
          pending.map((p: Proposal) => (
            <div key={p.proposal_id} className="proposal-row">
              <span className={p.direction === "long" ? "positive" : "negative"} style={{ fontWeight: 700 }}>
                {p.direction === "long" ? "BUY" : "SELL"}
              </span>
              <div className="meta">
                <b>{p.symbol}</b> @ {fmt(p.entry_price)} · SL {fmt(p.stop_loss)} · TP {fmt(p.take_profit)}
                <br />
                Size {p.position_size} lot(s) · risk {p.risk_pct}% · {p.timeframe}
                <br />
                <span className="reason">{p.reason_text}</span>
                <br />
                <span className="muted">signal {ts(p.created_at)}</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="btn approve"
                  disabled={busy === p.proposal_id}
                  onClick={() => void decide(p, true)}
                >
                  {busy === p.proposal_id ? "…" : "Approve"}
                </button>
                <button
                  className="btn reject"
                  disabled={busy === p.proposal_id}
                  onClick={() => void decide(p, false)}
                >
                  Reject
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="card">
        <h2>Recent decisions</h2>
        {decided.length === 0 ? (
          <p>Nothing decided yet.</p>
        ) : (
          <table className="simple">
            <thead>
              <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Status</th><th>Reason</th></tr>
            </thead>
            <tbody>
              {decided.map((p: Proposal) => (
                <tr key={p.proposal_id}>
                  <td>{ts(p.created_at)}</td>
                  <td>{p.symbol}</td>
                  <td className={p.direction === "long" ? "positive" : "negative"}>
                    {p.direction.toUpperCase()}
                  </td>
                  <td>{fmt(p.entry_price)}</td>
                  <td><span className={`badge ${p.status}`}>{p.status}</span></td>
                  <td className="muted">{p.decision_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default TradeApproval
