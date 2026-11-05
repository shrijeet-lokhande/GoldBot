import React, { useEffect, useState } from "react"
import { apiGet, apiPost, fmt } from "../../lib/api"
import { EngineState } from "../../lib/useEngineState"

const SystemHealth: React.FC<{ state: EngineState }> = ({ state }) => {
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const health = state.health
  const [status, setStatus] = useState<Record<string, any> | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const s = await apiGet<Record<string, any>>("/api/v1/engine/status")
        if (!cancelled) setStatus(s)
      } catch {
        /* ignore */
      }
    }
    void load()
    const interval = setInterval(load, 2500)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const toggleEngine = async (start: boolean) => {
    setBusy(start ? "start" : "stop")
    setNotice(null)
    try {
      const result = start
        ? await apiPost<any>("/api/v1/engine/start", { interval_seconds: 1.0 })
        : await apiPost<any>("/api/v1/engine/stop")
      setNotice(result.status)
    } catch (e: any) {
      setNotice(e?.message)
    } finally {
      setBusy(null)
    }
  }

  const toggleKillSwitch = async (active: boolean) => {
    setBusy(active ? "ks-on" : "ks-off")
    setNotice(null)
    try {
      await apiPost("/api/v1/risk/kill-switch", {
        active,
        reason: active ? "operator dashboard" : "manual",
      })
      setNotice(active ? "Kill switch ACTIVATED - new entries blocked." : "Kill switch cleared.")
    } catch (e: any) {
      setNotice(e?.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="page">
      <h1>System health</h1>
      {notice && <div className="card"><p>{notice}</p></div>}

      <div className="card">
        <h2>Controls</h2>
        <div className="toolbar">
          <button className="btn approve" disabled={busy !== null}
                  onClick={() => void toggleEngine(true)}>
            {busy === "start" ? "Starting…" : "Start replay loop"}
          </button>
          <button className="btn reject" disabled={busy !== null}
                  onClick={() => void toggleEngine(false)}>
            {busy === "stop" ? "Stopping…" : "Stop replay loop"}
          </button>
          {health && (
            <span className="badge">{health.kill_switch ? "KILL SWITCH ACTIVE" : "kill switch off"}</span>
          )}
        </div>
        <div className="toolbar">
          <button className="btn reject" disabled={busy !== null || health?.kill_switch}
                  onClick={() => void toggleKillSwitch(true)}>
            Activate kill switch
          </button>
          <button className="btn secondary" disabled={busy !== null || !health?.kill_switch}
                  onClick={() => void toggleKillSwitch(false)}>
            Clear kill switch
          </button>
        </div>
      </div>

      <div className="card">
        <h2>Engine</h2>
        {!health ? (
          <p>Loading…</p>
        ) : (
          <>
            <div className="grid">
              <div className="stat-line">Status<b className={health.status === "ok" ? "positive" : "negative"}>
                {health.status}</b></div>
              <div className="stat-line">Mode<b>{health.mode}</b></div>
              <div className="stat-line">Replay position<b>
                {fmt(health.replay_index, 0)} / {fmt(health.total_bars, 0)} bars</b></div>
              <div className="stat-line">Layer status<b className={health.paper_broker_healthy ? "positive" : "negative"}>
                {health.paper_broker_healthy ? "broker healthy" : "broker down"}</b></div>
            </div>
            <div className="spacer-gap" />
            <div className="kv"><span>Data source</span><span>{health.data_source}</span></div>
            <div className="kv"><span>Metadata verified</span><span>{health.metadata_verified ? "yes" : "no"}</span></div>
            <div className="kv"><span>Environment</span><span>{health.environment}</span></div>
            {health.kill_switch_reasons.length > 0 && (
              <div className="kv"><span>Kill switch reasons</span>
                <span className="negative">{health.kill_switch_reasons.join(", ")}</span></div>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2>Live feed</h2>
        {(status?.websocket_clients ?? 0) > 0 ? (
          <p>Dashboards connected: {status?.websocket_clients} — event stream active.</p>
        ) : (
          <p>No dashboards connected via WebSocket yet.</p>
        )}
        <p className="muted">Last engine events (newest first):</p>
        <div style={{ maxHeight: 260, overflowY: "auto" }}>
          {state.events.length === 0 ? (
            <p className="muted">Waiting for events…</p>
          ) : (
            state.events.slice(0, 25).map((e, i: number) => (
              <div key={i} className="kv">
                <span>{new Date(e.at).toLocaleTimeString()} · {e.type}</span>
                <span style={{ textAlign: "right" }}>
                  {e.type === "candle" ? `close ${fmt(e.data.close)}` :
                    e.type === "price" ? `bid ${fmt(e.data.bid)} ask ${fmt(e.data.ask)}` :
                    e.type === "proposal" ? `${e.data.direction} ${e.data.status}` :
                    e.type === "trade" ? `${e.data.reason} P&L ${fmt(e.data.pnl)}` : "…"}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

export default SystemHealth
