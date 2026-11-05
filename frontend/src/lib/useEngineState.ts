// Shared live engine state via WebSocket, with graceful REST polling fallback.

import { useEffect, useMemo, useRef, useState } from "react"
import {
  Account,
  CandleBar,
  Health,
  Position,
  Proposal,
  Quote,
  apiGet,
} from "./api"

export const IndicatorsSnapshot = {
  series: {} as Record<string, number[]>,
}

export interface EngineState {
  connected: boolean
  quote: Quote | null
  account: Account | null
  positions: Position[]
  proposals: Proposal[]
  candles: CandleBar[]
  health: Health | null
  indicators: Record<string, any>
  events: { type: string; data: any; at: number }[]
}

const WS_DISABLED = import.meta.env.VITE_NO_WS === "1"

/**
 * Holds the live dashboard state. Use WebSocket when available; otherwise
 * poll the REST endpoints every couple of seconds so the UI remains usable.
 */
export function useEngineState(): EngineState {
  const [connected, setConnected] = useState(false)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [candles, setCandles] = useState<CandleBar[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [indicators, setIndicators] = useState<Record<string, any>>({})
  const [events, setEvents] = useState<{ type: string; data: any; at: number }[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  // First paint from REST so the dashboard is never empty.
  useEffect(() => {
    let cancelled = false
    const primed = async () => {
      try {
        const [h, q, a, p, props, c] = await Promise.all([
          apiGet<Health>("/api/v1/health"),
          apiGet<Quote>("/api/v1/quote"),
          apiGet<Account>("/api/v1/account"),
          apiGet<Position[]>("/api/v1/positions"),
          apiGet<Proposal[]>("/api/v1/proposals"),
          apiGet<{ candles: CandleBar[] }>("/api/v1/candles?limit=300"),
        ])
        if (cancelled) return
        setHealth(h)
        setQuote(q)
        setAccount(a)
        setPositions(p)
        setProposals(props)
        setCandles(c.candles)
      } catch {
        /* backend may still be booting; WS/next poll will fill in */
      }
    }
    primed()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (WS_DISABLED) return
    const proto = window.location.protocol === "https:" ? "wss" : "ws"
    const wsUrl = `${proto}://${window.location.host}/ws`
    let socket: WebSocket
    let closedByUs = false
    let retry: ReturnType<typeof setTimeout> | undefined

    const connect = () => {
      socket = new WebSocket(wsUrl)
      wsRef.current = socket

      socket.onopen = () => setConnected(true)
      socket.onclose = () => {
        setConnected(false)
        if (!closedByUs) {
          retry = setTimeout(connect, 2000) // auto-reconnect
        }
      }
      socket.onerror = () => socket.close()

      socket.onmessage = (msg) => {
        try {
          const evt = JSON.parse(msg.data)
          const d = evt.data ?? {}
          switch (evt.type) {
            case "snapshot":
              setHealth(d.health)
              setQuote(d.quote)
              setAccount(d.account)
              setPositions(d.positions)
              setProposals(d.proposals)
              setCandles(d.candles)
              if (d.indicators) setIndicators(d.indicators)
              break
            case "candle":
              setCandles((prev) => {
                const next = [...prev, d]
                return next.slice(-1000)
              })
              break
            case "price":
              setQuote(d)
              if (typeof d.equity === "number") {
                setAccount((a) =>
                  a ? { ...a, equity: d.equity } : a
                )
              }
              break
            case "proposal":
              setProposals((prev) => {
                const next = prev.filter(
                  (p: Proposal) => p.proposal_id !== d.proposal_id
                )
                return d.status === "pending" ? [...next, d] : [...next, d]
              })
              break
            case "order":
              setProposals((prev) =>
                prev.map((p: Proposal) =>
                  p.proposal_id === d.proposal_id
                    ? { ...p, status: "executed", order_id: d.order_id }
                    : p
                )
              )
              break
            case "trade":
              setProposals((prev) => prev)
              break
            case "risk":
              if (d.status) setHealth(d)
              break
          }
          setEvents((prev) =>
            [{ type: evt.type, data: d, at: Date.now() }, ...prev].slice(0, 80)
          )
        } catch {
          /* ignore malformed frames */
        }
      }
    }

    connect()
    return () => {
      closedByUs = true
      window.clearTimeout(retry)
      socket?.close()
    }
  }, [])

  // REST fallback polling when the socket is down (and top-ups when live).
  useEffect(() => {
    const interval = setInterval(async () => {
      if (connected) return
      try {
        const [h, q, a, p] = await Promise.all([
          apiGet<Health>("/api/v1/health"),
          apiGet<Quote>("/api/v1/quote"),
          apiGet<Account>("/api/v1/account"),
          apiGet<Position[]>("/api/v1/positions"),
        ])
        setHealth(h)
        setQuote(q)
        setAccount(a)
        setPositions(p)
      } catch {
        /* keep last known state */
      }
    }, 2500)
    return () => clearInterval(interval)
  }, [connected])

  return useMemo(
    () => ({
      connected,
      quote,
      account,
      positions,
      proposals,
      candles,
      health,
      indicators,
      events,
    }),
    [connected, quote, account, positions, proposals, candles, health, indicators, events],
  )
}
