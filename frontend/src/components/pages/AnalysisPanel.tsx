import React, { useEffect, useState } from "react"
import { apiGet } from "../../lib/api"

// Mirrors goldbot.analysis.report.AnalysisReport.to_dict().

interface AnalysisReport {
  symbol: string
  generated_at_utc: string
  market_regime: string
  directional_bias: string
  htf_trend: string | null
  ltf_setup: string | null
  support_levels: number[]
  resistance_levels: number[]
  liquidity_levels: Record<string, number>
  volatility: Record<string, number>
  confidence: Record<string, unknown>
  avoid_trading_reasons: string[]
  trade_plan: {
    direction: string
    entry_zones: Array<[number, number]>
    invalidation_level: number
    stop_loss: number
    take_profits: number[]
    risk_reward_ratio: number
  } | null
  data_quality: Record<string, unknown>
  structure: Record<string, unknown>
  timeframes: Record<string, Record<string, unknown>>
  reference_levels: Record<string, unknown>
}

const fmtPx = (v: number): string => v.toFixed(2)

const tfRow = (tfs: Record<string, Record<string, unknown>>): Array<[string, string, string]> =>
  Object.entries(tfs).map(([tf, v]) => [
    tf,
    String(v.trend ?? "—"),
    String(v.vote ?? v.weight ?? ""),
  ])

const AnalysisPanel: React.FC = () => {
  const [report, setReport] = useState<AnalysisReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void apiGet<AnalysisReport>("/api/v1/analysis")
      .then(setReport)
      .catch((e: Error) => setError(e.message))
  }, [])

  const biasClass =
    report?.directional_bias === "bullish"
      ? "positive"
      : report?.directional_bias === "bearish"
        ? "negative"
        : "muted"

  return (
    <div className="page">
      <h1>Analysis</h1>
      <p className="muted">
        Structured XAUUSD market analysis from GoldBot's own validated
        indicator + market-structure pipeline (TradingView is display-only).
        Thresholds documented in docs/THRESHOLDS.md.
      </p>
      {error && <div className="card negative">Failed to load analysis: {error}</div>}
      {report && (
        <>
          <div className="card">
            <h2>Market snapshot</h2>
            <div className="grid">
              <div className="stat-line">Instrument<b>{report.symbol}</b></div>
              <div className="stat-line">
                Generated<b className="muted">{report.generated_at_utc}</b>
              </div>
              <div className="stat-line">Regime<b>{report.market_regime}</b></div>
              <div className="stat-line">
                Bias<b className={biasClass}>{report.directional_bias}</b>
              </div>
              <div className="stat-line">HTF trend<b>{report.htf_trend ?? "—"}</b></div>
              <div className="stat-line">LTF setup<b>{report.ltf_setup ?? "—"}</b></div>
            </div>
            {report.avoid_trading_reasons?.length > 0 && (
              <p className="negative">Avoid trading: {report.avoid_trading_reasons.join("; ")}</p>
            )}
          </div>

          {report.trade_plan && (
            <div className="card">
              <h2>Trade plan ({report.trade_plan.direction})</h2>
              <div className="grid">
                <div className="stat-line">
                  Entry zones<b>
                    {report.trade_plan.entry_zones
                      .map((z) => `${fmtPx(z[0])}–${fmtPx(z[1])}`)
                      .join(", ") || "—"}
                  </b>
                </div>
                <div className="stat-line">
                  Stop<b className="negative">{fmtPx(report.trade_plan.stop_loss)}</b>
                </div>
                <div className="stat-line">
                  Targets<b className="positive">
                    {report.trade_plan.take_profits.map(fmtPx).join(", ") || "—"}
                  </b>
                </div>
                <div className="stat-line">
                  Invalidation<b className="muted">{fmtPx(report.trade_plan.invalidation_level)}</b>
                </div>
                <div className="stat-line">
                  R:R<b>{fmtPx(report.trade_plan.risk_reward_ratio)}</b>
                </div>
              </div>
            </div>
          )}

          <div className="card">
            <h2>Multi-timeframe context</h2>
            <table>
              <thead>
                <tr>
                  <th>Timeframe</th>
                  <th>Trend</th>
                  <th>Vote</th>
                </tr>
              </thead>
              <tbody>
                {tfRow(report.timeframes ?? {}).map(([tf, trend, vote]) => (
                  <tr key={tf}>
                    <td>{tf}</td>
                    <td>{trend}</td>
                    <td>{vote}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h2>Reference levels (session / PD / PW)</h2>
            <table>
              <thead>
                <tr>
                  <th>Level</th>
                  <th>High</th>
                  <th>Low</th>
                  <th>Window</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(report.reference_levels ?? {})
                  .filter(
                    ([, v]) => typeof v === "object" && v !== null && "high" in (v as object)
                  )
                  .map(([k, v]) => {
                    const lv = v as { high: number; low: number; start_utc: string }
                    return (
                      <tr key={k}>
                        <td>{k}</td>
                        <td>{fmtPx(lv.high)}</td>
                        <td>{fmtPx(lv.low)}</td>
                        <td className="muted">{lv.start_utc}</td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
            <p className="muted small">
              Sessions (UTC): {String(
                (report.reference_levels?.sessions_utc as Record<string, string>)?.asia ?? ""
              )}{" "}
              Asia · {(report.reference_levels?.sessions_utc as Record<string, string>)?.london}{" "}
              London · {(report.reference_levels?.sessions_utc as Record<string, string>)?.new_york}{" "}
              NY
            </p>
          </div>

          <div className="card">
            <h2>Key levels</h2>
            <div className="grid">
              <div className="stat-line">
                Support<b>{(report.support_levels ?? []).map(fmtPx).join(", ") || "—"}</b>
              </div>
              <div className="stat-line">
                Resistance<b>{(report.resistance_levels ?? []).map(fmtPx).join(", ") || "—"}</b>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default AnalysisPanel
