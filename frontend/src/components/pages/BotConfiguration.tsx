import React, { useEffect, useState } from "react"
import { EngineConfig, apiGet, apiPost } from "../../lib/api"

const BotConfiguration: React.FC = () => {
  const [config, setConfig] = useState<EngineConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      setConfig(await apiGet<EngineConfig>("/api/v1/config"))
    } catch (e: any) {
      setError(e?.message)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const setField = (key: keyof EngineConfig, value: unknown) => {
    if (!config) return
    setConfig({ ...config, [key]: value } as EngineConfig)
  }

  const save = async () => {
    if (!config) return
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const payload = {
        risk_per_trade_pct: config.risk_per_trade_pct,
        daily_loss_limit_pct: config.daily_loss_limit_pct,
        weekly_drawdown_limit_pct: config.weekly_drawdown_limit_pct,
        max_open_positions: config.max_open_positions,
        max_entries_per_day: config.max_entries_per_day,
        max_consecutive_losses: config.max_consecutive_losses,
        auto_approve: config.auto_approve,
      }
      const updated = await apiPost<EngineConfig>("/api/v1/config", payload)
      setConfig(updated)
      setNotice("Configuration applied to the running engine.")
    } catch (e: any) {
      setError(e?.message ?? "Save failed")
    } finally {
      setSaving(false)
    }
  }

  const numField = (
    key: keyof EngineConfig,
    label: string,
    step: "any" = "any",
  ) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span className="muted" style={{ fontSize: "0.78rem" }}>{label}</span>
      <input
        type="number"
        step={step}
        value={config?.[key] as any as number}
        onChange={(e) => setField(key, e.target.value === "" ? 0 : Number(e.target.value))}
        style={{
          background: "var(--bg-secondary)", color: "var(--fg)",
          border: "1px solid var(--border)", borderRadius: 6,
          padding: "7px 10px", minWidth: 130,
        }}
      />
    </label>
  )

  if (error && !config) {
    return (
      <div className="page">
        <h1>Configuration</h1>
        <div className="card"><p className="negative">{error}</p></div>
      </div>
    )
  }
  if (!config) {
    return <div className="page"><h1>Configuration</h1><p>Loading…</p></div>
  }

  return (
    <div className="page">
      <h1>Configuration</h1>
      {notice && <div className="card"><p className="positive">{notice}</p></div>}
      {error && <div className="card"><p className="negative">{error}</p></div>}

      <div className="card">
        <h2>Identity</h2>
        <div className="grid">
          <div className="stat-line">Instrument<b>{config.instrument_symbol}</b></div>
          <div className="stat-line">Mode<b>{config.mode}</b></div>
          <div className="stat-line">Environment<b>{config.environment}</b></div>
          <div className="stat-line">Strategy<b>{config.strategy_name}</b></div>
          <div className="stat-line">Entry timeframe<b>{config.entry_timeframe}</b></div>
          <div className="stat-line">Trend timeframe<b>{config.trend_timeframe}</b></div>
        </div>
      </div>

      <div className="card">
        <h2>Risk & execution (live-safe updates)</h2>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
          {numField("risk_per_trade_pct", "Risk per trade (%)")}
          {numField("daily_loss_limit_pct", "Daily loss limit (%)")}
          {numField("weekly_drawdown_limit_pct", "Weekly drawdown limit (%)")}
          {numField("max_open_positions", "Max open positions")}
          {numField("max_entries_per_day", "Max entries per day")}
          {numField("max_consecutive_losses", "Max consecutive losses")}
        </div>
        <div className="spacer-gap" />
        <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={config.auto_approve}
            onChange={(e) => setField("auto_approve", e.target.checked)}
          />
          <span>Auto-approve proposals that pass all risk checks</span>
        </label>
        <div className="spacer-gap" />
        <div className="toolbar">
          <button className="btn approve" disabled={saving} onClick={() => void save()}>
            {saving ? "Saving…" : "Apply to engine"}
          </button>
          <button className="btn secondary" onClick={() => void load()} disabled={saving}>
            Reload from engine
          </button>
        </div>
      </div>

      <p className="muted">
        Changes take effect immediately on the running engine and are validated by the
        risk engine (non-positive or out-of-range values are ignored).
      </p>
    </div>
  )
}

export default BotConfiguration
