import React, { useEffect, useState } from "react"
import { apiGet, fetchInstrument, InstrumentIdentity } from "../../lib/api"

// Types mirror /api/v1/prediction (goldbot.prediction.PredictionResult.to_dict).

interface Evaluation {
  train_rows: number
  test_rows: number
  directional_accuracy: number
  baseline_majority_accuracy: number
  momentum_accuracy: number
  brier_score: number | null
  log_loss: number | null
  calibration_bins: Array<{
    bin: string
    rows: number
    empirical_up_rate: number | null
  }>
  walk_forward_folds: Array<{ train_rows: number; test_rows: number; accuracy: number }>
  walk_forward_accuracy: number | null
  beats_baselines: boolean | null
}

interface Forecast {
  directional_bias: "up" | "down" | "neutral"
  regime: string
  entry_zone: [number, number]
  invalidation_level: number
  stop_loss: number
  take_profit: number
  risk_reward: number
  horizon: string
  confidence: number
  supporting_evidence: string[]
  probability_up: number
  disclaimer: string
}

interface PredictionResponse {
  available?: boolean
  detail?: string
  data_limitation?: string
  forecast?: Forecast
  features_used?: string[]
  model_coefficients?: Record<string, number>
  evaluation?: Evaluation | null
}

const pct = (v: number | null | undefined): string =>
  typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—"

const fmtPx = (v: number): string => v.toFixed(2)

const Prediction: React.FC = () => {
  const [data, setData] = useState<PredictionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [identity, setIdentity] = useState<InstrumentIdentity | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  useEffect(() => {
    void fetchInstrument().then(setIdentity).catch(() => setIdentity(null))
  }, [])

  const load = () => {
    setError(null)
    void apiGet<PredictionResponse>("/api/v1/prediction")
      .then((d) => {
        setData(d)
        setFetchedAt(new Date().toISOString())
      })
      .catch((e: Error) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [])

  const biasClass =
    data?.forecast?.directional_bias === "up"
      ? "positive"
      : data?.forecast?.directional_bias === "down"
        ? "negative"
        : "muted"

  return (
    <div className="page">
      <h1>Prediction</h1>
      <p className="muted">
        Statistical forecast for {identity?.symbol ?? "XAUUSD"} from validated candle
        history. Confidence is a heuristic score — <b>not</b> a calibrated probability;
        the evaluation block below is where real out-of-sample skill is shown.
      </p>

      {error && <div className="card negative">Failed to load prediction: {error}</div>}

      {data && !data.available && data.detail && (
        <div className="card">
          <h2>Forecast unavailable</h2>
          <p>{data.detail}</p>
          <p className="muted">{data.data_limitation}</p>
          <button onClick={load}>Retry</button>
        </div>
      )}

      {data?.forecast && (
        <>
          <div className="card">
            <h2>Forecast</h2>
            <div className="grid">
              <div className="stat-line">
                Directional bias
                <b className={biasClass}>{data.forecast.directional_bias.toUpperCase()}</b>
              </div>
              <div className="stat-line">
                Regime<b>{data.forecast.regime}</b>
              </div>
              <div className="stat-line">
                Horizon<b>{data.forecast.horizon}</b>
              </div>
              <div className="stat-line">
                Confidence (heuristic)<b>{data.forecast.confidence}/90</b>
              </div>
              <div className="stat-line">
                Model P(up)<b className="muted">{pct(data.forecast.probability_up)}</b>
              </div>
              <div className="stat-line">
                Risk:Reward<b>{fmtPx(data.forecast.risk_reward)}</b>
              </div>
            </div>
            <div className="grid">
              <div className="stat-line">
                Entry zone
                <b>
                  {fmtPx(data.forecast.entry_zone[0])} – {fmtPx(data.forecast.entry_zone[1])}
                </b>
              </div>
              <div className="stat-line">
                Stop loss<b className="negative">{fmtPx(data.forecast.stop_loss)}</b>
              </div>
              <div className="stat-line">
                Take profit<b className="positive">{fmtPx(data.forecast.take_profit)}</b>
              </div>
              <div className="stat-line">
                Invalidation<b className="muted">{fmtPx(data.forecast.invalidation_level)}</b>
              </div>
            </div>
            <p className="muted small">{data.forecast.disclaimer}</p>
            {fetchedAt && (
              <p className="muted small">Computed at: {fetchedAt} (local clock)</p>
            )}
          </div>

          <div className="card">
            <h2>Supporting evidence</h2>
            <ul>
              {data.forecast.supporting_evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>

          {data.evaluation && (
            <div className="card">
              <h2>Out-of-sample evaluation</h2>
              <div className="grid">
                <div className="stat-line">
                  Model accuracy (test)<b>{pct(data.evaluation.directional_accuracy)}</b>
                </div>
                <div className="stat-line">
                  Majority baseline<b className="muted">
                    {pct(data.evaluation.baseline_majority_accuracy)}
                  </b>
                </div>
                <div className="stat-line">
                  Momentum baseline<b className="muted">{pct(data.evaluation.momentum_accuracy)}</b>
                </div>
                <div className="stat-line">
                  Walk-forward accuracy<b>{pct(data.evaluation.walk_forward_accuracy)}</b>
                </div>
                <div className="stat-line">
                  Brier score<b>{data.evaluation.brier_score?.toFixed(4) ?? "—"}</b>
                </div>
                <div className="stat-line">
                  Beats baselines<b
                    className={data.evaluation.beats_baselines ? "positive" : "negative"}
                  >
                    {data.evaluation.beats_baselines ? "YES" : "NO"}
                  </b>
                </div>
              </div>
              <p className="muted small">
                Chronological split only (train {data.evaluation.train_rows} / test{" "}
                {data.evaluation.test_rows} rows, never shuffled). Calibration bins show the
                empirical up-rate inside each predicted-probability bucket — how close
                "confidence" is to a real probability.
              </p>
              <table>
                <thead>
                  <tr>
                    <th>P(up) bin</th>
                    <th>Rows</th>
                    <th>Empirical up-rate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.evaluation.calibration_bins.map((b) => (
                    <tr key={b.bin}>
                      <td>{b.bin}</td>
                      <td>{b.rows}</td>
                      <td>{pct(b.empirical_up_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="card">
            <h2>Model transparency</h2>
            <p className="muted small">
              Logistic regression on standardised features; coefficients below are the
              complete model — nothing hidden.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Weight</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.model_coefficients ?? {}).map(([k, v]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{v.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <button onClick={load}>Recompute</button>
    </div>
  )
}

export default Prediction
