import React, { useCallback, useEffect, useState } from "react"
import {
  BrokerConnectionStatus,
  AuditTrailEntry,
  authorizeLive,
  fetchConnectionStatus,
  fetchModeAudit,
  switchMode,
  verifyBroker,
} from "../../lib/api"

// Account connections + trading-mode selector.
//
// Safety rules enforced here and server-side:
// - Paper trading is the default; live requires a connected broker AND a
//   typed confirmation phrase, confirmed twice (authorize + switch).
// - No "Sign in with TradingView": TradingView consumer accounts offer no
//   generic OAuth for trading bots, and fake auth is prohibited. TradingView
//   remains charting-only.
// - Broker credentials are configured via environment (GOLD_OANDA_*); this
//   page never collects or stores them.

const CONFIRMATION_PHRASE = "ENABLE LIVE TRADING"

const AccountConnections: React.FC = () => {
  const [status, setStatus] = useState<BrokerConnectionStatus | null>(null)
  const [audit, setAudit] = useState<AuditTrailEntry[]>([])
  const [confirmation, setConfirmation] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [conn, trail] = await Promise.all([
        fetchConnectionStatus(),
        fetchModeAudit(),
      ])
      setStatus(conn)
      setAudit(trail.slice(-15).reverse())
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), 10_000)
    return () => window.clearInterval(id)
  }, [refresh])

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await fn()
      setMessage(ok)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const mode = status?.mode.mode ?? "paper"

  return (
    <section className="page">
      <header className="page-head">
        <h2>Trading mode &amp; accounts</h2>
        <span className={`mode-badge ${mode}`}>
          {mode === "live" ? "● LIVE TRADING" : "● PAPER TRADING"}
        </span>
      </header>

      {message && <p className="ok">{message}</p>}
      {error && <p className="err">{error}</p>}

      <div className="cards">
        <div className="card">
          <h3>Execution mode</h3>
          <p className="muted">
            Paper trading is the default and never touches a broker. Switching
            to live requires a connected broker account and explicit typed
            confirmation. Switching modes never moves, duplicates, or closes
            existing positions.
          </p>
          <div className="mode-buttons">
            <button
              disabled={busy || mode === "paper"}
              onClick={() => act(() => switchMode("paper"), "Switched to paper trading")}
            >
              PAPER TRADING
            </button>
            <button
              className="danger"
              disabled={busy || mode === "live"}
              onClick={() => act(() => switchMode("live"), "LIVE TRADING ENABLED")}
            >
              LIVE TRADING
            </button>
          </div>

          <div className="field">
            <label>
              Live authorization — type{" "}
              <code>{CONFIRMATION_PHRASE}</code> to authorize:
            </label>
            <input
              type="text"
              value={confirmation}
              placeholder={CONFIRMATION_PHRASE}
              onChange={(e) => setConfirmation(e.target.value)}
            />
            <button
              disabled={busy || confirmation !== CONFIRMATION_PHRASE}
              onClick={() =>
                act(async () => {
                  await authorizeLive(confirmation)
                  setConfirmation("")
                }, "Live execution authorized (still requires switching mode)")
              }
            >
              Authorize live execution
            </button>
          </div>
          <p className="muted">
            Authorization state: {String(status?.mode.live_authorized ?? false)} ·
            Broker connected: {String(status?.mode.broker_connected ?? false)}
          </p>
        </div>

        <div className="card">
          <h3>Broker account (OANDA v20 REST)</h3>
          <p className="muted">
            Configured via environment variables only — GoldBot never stores
            broker credentials or tokens:
          </p>
          <ul className="muted">
            <li><code>GOLD_OANDA_ACCOUNT_ID</code></li>
            <li><code>GOLD_OANDA_API_TOKEN</code> (personal access token)</li>
            <li><code>GOLD_OANDA_ENVIRONMENT</code> = practice | live</li>
          </ul>
          <button
            disabled={busy}
            onClick={() => act(() => verifyBroker(), "Broker connection verified")}
          >
            Verify broker connection
          </button>
          <dl className="kv">
            <dt>Adapter</dt>
            <dd>{status?.broker.adapter ?? "not configured"}</dd>
            <dt>Environment</dt>
            <dd>
              {status?.broker.environment ?? "—"}
              {status?.broker.environment === "live" && (
                <strong className="err"> LIVE (real money)</strong>
              )}
            </dd>
            <dt>Balance</dt>
            <dd>
              {status?.broker.account_summary &&
              "balance" in status.broker.account_summary
                ? String(status.broker.account_summary.balance)
                : "—"}
            </dd>
            <dt>Available margin</dt>
            <dd>
              {status?.broker.account_summary &&
              "available_margin" in status.broker.account_summary
                ? String(status.broker.account_summary.available_margin)
                : "—"}
            </dd>
          </dl>
          <h3>TradingView account</h3>
          <p className="muted">
            TradingView provides the chart display only. TradingView consumer
            accounts do not offer OAuth for third-party trading bots, so
            GoldBot does not implement (or fake) “Sign in with TradingView”.
            Market data and execution use independent, properly authenticated
            services.
          </p>
        </div>
      </div>

      <h3>Mode-change audit trail</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Time (UTC)</th>
            <th>Event</th>
            <th>Actor</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {audit.map((entry, i) => (
            <tr key={i}>
              <td>{entry.timestamp_utc}</td>
              <td>{entry.event}</td>
              <td>{entry.actor}</td>
              <td className="muted">{JSON.stringify(entry.details)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export default AccountConnections
