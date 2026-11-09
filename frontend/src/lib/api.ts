// REST + WebSocket client for the GoldBot backend.

export const API_BASE = import.meta.env.VITE_API_BASE ?? ""

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status} ${detail}`)
  }
  return res.json() as Promise<T>
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? "{}" : JSON.stringify(body),
  })
  const text = await res.text().catch(() => "")
  if (!res.ok) {
    let detail = text
    try {
      detail = JSON.parse(text)?.detail ?? text
    } catch {
      /* keep raw text */
    }
    throw new Error(`${res.status} ${detail}`)
  }
  return (text ? JSON.parse(text) : {}) as T
}

// ---------------------------------------------------------------------------
// Types matching the backend payloads
// ---------------------------------------------------------------------------

export interface Quote {
  bid: number
  ask: number
  spread: number
  mid_price: number
  equity?: number
}

export interface Account {
  balance: number
  equity: number
  realised_pnl: number
  unrealised_pnl: number
  initial_equity: number
}

export interface Position {
  symbol: string
  direction: "LONG" | "SHORT"
  volume: number
  entry_price: number
  current_price: number
  unrealised_pnl: number
  realised_pnl: number
  stop_loss: number | null
  take_profit: number | null
  pnl_percent: number
}

export interface Proposal {
  proposal_id: string
  symbol: string
  direction: "long" | "short"
  entry_price: number
  stop_loss: number
  take_profit: number
  position_size: number
  risk_pct: number
  reason_text: string
  confidence: string
  strategy_name: string
  timeframe: string
  created_at: string
  status: "pending" | "approved" | "rejected" | "expired" | "executed"
  decision_reason: string | null
  order_id: string | null
}

export interface Trade {
  trade_id: string
  symbol: string
  side: "buy" | "sell"
  volume: number
  entry_price: number
  close_price: number
  pnl: number
  entry_time?: string
  close_time: string
  reason: string
}

export interface Perf {
  total_trades: number
  win_rate: number
  profit_factor: number | null
  total_pnl: number
  average_win: number
  average_loss: number
  max_drawdown_pct: number
  current_equity: number
}

export interface Health {
  status: string
  mode: string
  environment: string
  instrument_symbol: string
  metadata_verified: boolean
  running: boolean
  replay_index: number
  total_bars: number
  paper_broker_healthy: boolean
  data_source: string
  kill_switch: boolean
  kill_switch_reasons: string[]
}

export interface EngineConfig {
  instrument_symbol: string
  mode: string
  environment: string
  risk_per_trade_pct: number
  daily_loss_limit_pct: number
  weekly_drawdown_limit_pct: number
  max_open_positions: number
  max_entries_per_day: number
  max_consecutive_losses: number
  strategy_name: string
  entry_timeframe: string
  trend_timeframe: string
  auto_approve: boolean
  replay_index: number
  total_bars: number
  api_version?: string
}

export interface CandleBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// ---------------------------------------------------------------------------
// Trading mode + broker connections (v2)
// ---------------------------------------------------------------------------

export interface ModeStatus {
  mode: "paper" | "live"
  live_authorized: boolean
  broker_connected: boolean
  confirmation_phrase_required: string
}

export interface BrokerConnectionStatus {
  mode: ModeStatus
  broker: {
    adapter: string | null
    environment: string | null
    configured: boolean
    account_summary: Record<string, unknown> | null
    tradingview_oauth_available: boolean
  }
}

export interface AuditTrailEntry {
  timestamp_utc: string
  actor: string
  event: string
  details: Record<string, unknown>
}

export function fetchModeStatus(): Promise<ModeStatus> {
  return apiGet<ModeStatus>("/api/v1/mode")
}

export function fetchConnectionStatus(): Promise<BrokerConnectionStatus> {
  return apiGet<BrokerConnectionStatus>("/api/v1/connections")
}

export function fetchModeAudit(): Promise<AuditTrailEntry[]> {
  return apiGet<AuditTrailEntry[]>("/api/v1/mode/audit")
}

export function authorizeLive(
  confirmation: string
): Promise<ModeStatus> {
  return apiPost<ModeStatus>("/api/v1/mode/authorize-live", { confirmation })
}

export function switchMode(mode: string): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>("/api/v1/mode/switch", { mode })
}

export function verifyBroker(): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>("/api/v1/connections/broker/verify")
}

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}$${fmt(n)}`
}

export function ts(iso: string | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}
