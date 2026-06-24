// API client for the event-contract (binary up/down) signal system.

export interface LiveSignal {
  exchange: string
  symbol: string
  expiry_minutes: number
  direction: 'long' | 'short' | 'none'
  signal_minute: number | null
  price: number | null
}

export interface DailyStats {
  total: number
  wins: number
  losses: number
  pending: number
  settled: number
  win_rate: number
  loss_rate: number
  tz: string
}

export interface BacktestResult {
  symbol: string
  expiry_minutes: number
  signal?: string
  strategy?: string
  total: number
  wins: number
  win_rate: number
  net_pnl: number
  payout: number
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: 'no-store' })
  if (!r.ok) throw new Error(`${url} -> ${r.status}`)
  return r.json()
}

export function getLiveSignals(exchange = 'hyperliquid') {
  return get<{ signals: LiveSignal[] }>(`/api/event-contract/signals/live?exchange=${exchange}`)
}

export function getDailyStats() {
  return get<DailyStats>('/api/event-contract/stats/daily')
}

export function getOverview() {
  return get<any>('/api/event-contract/overview')
}

export function compareBacktest(exchange: string, symbol: string, expiry: number) {
  return get<{ order_flow: BacktestResult[]; ta: BacktestResult[] }>(
    `/api/event-contract/backtest/compare?exchange=${exchange}&symbol=${symbol}&expiry_minutes=${expiry}`,
  )
}

export interface EventContractConfig {
  symbols: string[]
  expiries: number[]
  payout: number
  default_signal: string
  daily_reset_tz: string
  signal_params: Record<string, { window: number; thr: number }>
}

export function getEventContractConfig() {
  return get<EventContractConfig>('/api/event-contract/config')
}

export function getStrategies() {
  return get<{ ta: string[]; order_flow: string[] }>('/api/event-contract/strategies')
}

export function updateEventContractConfig(patch: Partial<EventContractConfig>) {
  return fetch('/api/event-contract/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).then((r) => {
    if (!r.ok) throw new Error(`PUT /config -> ${r.status}`)
    return r.json() as Promise<EventContractConfig>
  })
}

export interface SignalCandle { time: number; open: number; high: number; low: number; close: number }
export interface SignalMarker {
  time: number
  direction: 'long' | 'short'
  result: 'win' | 'loss' | 'pending'
  entry_price: number
  settle_price: number | null
}
export interface SignalHistory {
  exchange: string
  symbol: string
  expiry_minutes: number
  candles: SignalCandle[]
  markers: SignalMarker[]
}

export function getSignalHistory(exchange: string, symbol: string, expiry: number, limit = 180) {
  return get<SignalHistory>(
    `/api/event-contract/signals/history?exchange=${exchange}&symbol=${symbol}&expiry_minutes=${expiry}&limit=${limit}`,
  )
}

// --- 高级 K 线分析 + 陷阱（坑） ---------------------------------------------

export interface AnalysisTrap { id: string; title: string; detail: string; severity: 'high' | 'medium' | 'low' }
export interface AnalysisReport {
  price: number
  bias: 'long' | 'short' | 'neutral'
  confidence: number
  trend: { direction: 'up' | 'down' | 'mixed'; strong: boolean; ema10: number; sma50: number; sma200: number }
  momentum: { rsi: number; macd_cross: 'bull' | 'bear'; macd_hist: number }
  volatility: { atr: number; bb_upper: number; bb_lower: number; bb_width: number }
  volume: { vwma: number; vol_z: number; price_vs_vwma: string }
  long_reasons: string[]
  short_reasons: string[]
  traps: AnalysisTrap[]
  summary: string
}

export function getAnalysis(symbol: string, exchange: string, period = '1m', limit = 300) {
  return get<{ available: boolean; report: AnalysisReport | null }>(
    `/api/event-contract/analysis?symbol=${symbol}&exchange=${exchange}&period=${period}&limit=${limit}`,
  )
}

export interface IndicatorDoc { key: string; name: string; cat: string; measures: string; usage: string; trap: string }
export function getKnowledge() {
  return get<{ indicators: IndicatorDoc[]; traps: AnalysisTrap[] }>('/api/event-contract/knowledge')
}

export function getKlineHistory(symbol: string, exchange: string, period = '1d', limit = 365) {
  return get<{ count: number; candles: SignalCandle[] }>(
    `/api/event-contract/klines/history?symbol=${symbol}&exchange=${exchange}&period=${period}&limit=${limit}`,
  )
}
