// Exchange SVG logos
export const HyperliquidLogo = ({ className = '' }: { className?: string }) => (
  <svg width="16" height="16" viewBox="0 0 144 144" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
    <path d="M144 71.6991C144 119.306 114.866 134.582 99.5156 120.98C86.8804 109.889 83.1211 86.4521 64.116 84.0456C39.9942 81.0113 37.9057 113.133 22.0334 113.133C3.5504 113.133 0 86.2428 0 72.4315C0 58.3063 3.96809 39.0542 19.736 39.0542C38.1146 39.0542 39.1588 66.5722 62.132 65.1073C85.0007 63.5379 85.4184 34.8689 100.247 22.6271C113.195 12.0593 144 23.4641 144 71.6991Z" fill="#50e3c2"/>
  </svg>
)

export const BinanceLogo = ({ className = '' }: { className?: string }) => (
  <img src="/static/binance_logo.svg" alt="Binance" width="16" height="16" className={className} />
)

// Exchange badge component
export const ExchangeBadge = ({ exchange, size = 'sm' }: { exchange: string; size?: 'sm' | 'xs' }) => {
  const isHyperliquid = exchange === 'hyperliquid'
  const textSize = size === 'xs' ? 'text-[10px]' : 'text-xs'
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${isHyperliquid ? 'bg-emerald-500/10 text-emerald-400' : 'bg-yellow-500/10 text-yellow-400'}`}>
      {isHyperliquid ? <HyperliquidLogo /> : <BinanceLogo />}
      <span className={textSize}>{isHyperliquid ? 'Hyperliquid' : 'Binance'}</span>
    </span>
  )
}

// Types
export interface SignalDefinition {
  id: number
  signal_name: string
  description: string | null
  trigger_condition: TriggerCondition
  enabled: boolean
  exchange: string
  created_at: string
  updated_at: string
}

export interface TriggerCondition {
  metric?: string
  operator?: string
  threshold?: number
  time_window?: string
  logic?: string
  conditions?: TriggerCondition[]
}

export interface SignalPool {
  id: number
  pool_name: string
  signal_ids: number[]
  symbols: string[]
  enabled: boolean
  logic: 'OR' | 'AND'
  exchange: string
  source_type?: 'market_signals' | 'wallet_tracking'
  source_config?: {
    addresses?: string[]
    event_types?: string[]
    sync_mode?: string
  }
  created_at: string
}

export interface MarketRegimeData {
  regime: string
  direction: string
  confidence: number
  details?: Record<string, unknown>
}

export interface SignalTriggerLog {
  id: number
  signal_id: number | null
  pool_id: number | null
  symbol: string
  trigger_value: Record<string, unknown> | null
  triggered_at: string
  market_regime: MarketRegimeData | null
}

export interface WalletTrackingRuntimeStatus {
  enabled: boolean
  status: string
  tier: string | null
  synced_addresses: string[]
  last_connected_at: string | null
  last_message_at: string | null
  last_event_at: string | null
  last_error: string | null
  active_wallet_pool_count: number
  token_synced_at: string | null
}

export function parseUtcNaiveString(value?: string | null): Date | null {
  if (!value) return null
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatWalletRuntimeTime(value?: string | null): string {
  const parsed = parseUtcNaiveString(value)
  return parsed ? parsed.toLocaleString() : '-'
}

export function formatWalletTier(t: (key: string, fallback?: string) => string, tier?: string | null): string {
  if (tier === 'paid') {
    return t('signals.walletTracking.tierPremium', 'Premium (second-level detection)')
  }
  if (tier === 'free') {
    return t('signals.walletTracking.tierFree', 'Free (minute-level detection)')
  }
  return '-'
}

export interface FactorItem {
  name: string
  category: string
  description: string
  expression: string
  source: string
}

export type PoolSourceType = 'market_signals' | 'wallet_tracking'

export const WALLET_EVENT_TYPES = [
  'position_change',
  'equity_change',
  'fill',
  'funding',
  'transfer',
  'liquidation',
]

export function formatWalletEventType(t: (key: string, fallback?: string) => string, eventType: string): string {
  switch (eventType) {
    case 'position_change':
      return t('signals.walletTracking.eventTypePositionChange', 'Position Change')
    case 'equity_change':
      return t('signals.walletTracking.eventTypeEquityChange', 'Equity Change')
    case 'fill':
      return t('signals.walletTracking.eventTypeFill', 'Trade Fill')
    case 'funding':
      return t('signals.walletTracking.eventTypeFunding', 'Funding')
    case 'transfer':
      return t('signals.walletTracking.eventTypeTransfer', 'Transfer')
    case 'liquidation':
      return t('signals.walletTracking.eventTypeLiquidation', 'Liquidation')
    default:
      return eventType
  }
}

export function formatWalletActionLabel(t: (key: string, fallback?: string) => string, action?: string | null): string {
  switch (action) {
    case 'open':
      return t('signals.walletTracking.actionOpen', 'Opened')
    case 'add':
      return t('signals.walletTracking.actionAdd', 'Increased')
    case 'reduce':
      return t('signals.walletTracking.actionReduce', 'Reduced')
    case 'close':
      return t('signals.walletTracking.actionClose', 'Closed')
    case 'flip':
      return t('signals.walletTracking.actionFlip', 'Flipped')
    case 'update':
      return t('signals.walletTracking.actionUpdate', 'Updated')
    default:
      return action || '-'
  }
}

export function formatWalletDirectionLabel(t: (key: string, fallback?: string) => string, direction?: string | null): string {
  switch (direction) {
    case 'long':
      return t('signals.walletTracking.directionLong', 'Long')
    case 'short':
      return t('signals.walletTracking.directionShort', 'Short')
    case 'flat':
      return t('signals.walletTracking.directionFlat', 'Flat')
    default:
      return direction || '-'
  }
}

export function formatWalletMetricValue(value: unknown, digits = 2): string | null {
  if (typeof value !== 'number' || Number.isNaN(value)) return null
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })
}

export function formatShortAddress(address?: string | null): string {
  if (!address) return '-'
  if (address.length <= 14) return address
  return `${address.slice(0, 6)}...${address.slice(-4)}`
}

export function sortByCreatedAtDesc<T extends { created_at?: string | null }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const aTime = parseUtcNaiveString(a.created_at)?.getTime() || 0
    const bTime = parseUtcNaiveString(b.created_at)?.getTime() || 0
    return bTime - aTime
  })
}

// API functions
export const API_BASE = '/api/signals'

export async function fetchSignals(): Promise<{ signals: SignalDefinition[]; pools: SignalPool[] }> {
  const res = await fetch(API_BASE)
  if (!res.ok) throw new Error('Failed to fetch signals')
  return res.json()
}

export async function createSignal(data: Partial<SignalDefinition>): Promise<SignalDefinition> {
  const res = await fetch(`${API_BASE}/definitions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create signal')
  return res.json()
}

export async function updateSignal(id: number, data: Partial<SignalDefinition>): Promise<SignalDefinition> {
  const res = await fetch(`${API_BASE}/definitions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update signal')
  return res.json()
}

export async function deleteSignal(id: number): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/definitions/${id}`, { method: 'DELETE' })
  return res.json()
}

export async function createPool(data: Partial<SignalPool>): Promise<SignalPool> {
  const res = await fetch(`${API_BASE}/pools`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create pool')
  return res.json()
}

export async function updatePool(id: number, data: Partial<SignalPool>): Promise<SignalPool> {
  const res = await fetch(`${API_BASE}/pools/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update pool')
  return res.json()
}

export async function deletePool(id: number): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/pools/${id}`, { method: 'DELETE' })
  return res.json()
}

// Create signal pool from AI-generated config
export async function createPoolFromConfig(config: {
  name: string
  symbol: string
  description?: string
  logic: string
  signals: Array<{ metric: string; operator: string; threshold: number; time_window?: string }>
  exchange?: string
}): Promise<{ success: boolean; pool: SignalPool; signals: SignalDefinition[] }> {
  const res = await fetch(`${API_BASE}/create-pool-from-config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to create pool' }))
    throw new Error(error.detail || 'Failed to create pool')
  }
  return res.json()
}

export async function fetchTriggerLogs(options: {
  poolId?: number
  symbol?: string
  limit?: number
  offset?: number
} = {}): Promise<{ logs: SignalTriggerLog[]; total: number }> {
  const { poolId, symbol, limit = 50, offset = 0 } = options
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (poolId) params.set('pool_id', String(poolId))
  if (symbol) params.set('symbol', symbol)
  const res = await fetch(`${API_BASE}/logs?${params}`)
  if (!res.ok) throw new Error('Failed to fetch logs')
  return res.json()
}

export async function fetchWalletTrackingStatus(): Promise<WalletTrackingRuntimeStatus> {
  const res = await fetch(`${API_BASE}/wallet-tracking/status`)
  if (!res.ok) throw new Error('Failed to fetch wallet tracking status')
  return res.json()
}

export async function updateWalletTrackingRuntime(data: { enabled: boolean; access_token?: string }): Promise<WalletTrackingRuntimeStatus> {
  const res = await fetch(`${API_BASE}/wallet-tracking/runtime`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update wallet tracking runtime')
  return res.json()
}

export async function fetchPoolBacktest(poolId: number, symbol: string): Promise<any> {
  const params = new URLSearchParams({ symbol })
  const res = await fetch(`${API_BASE}/pool-backtest/${poolId}?${params}`)
  if (!res.ok) throw new Error('Failed to fetch pool backtest')
  return res.json()
}

// Market Regime batch query
export interface MarketRegimeResult {
  symbol: string
  regime: string
  direction: string
  confidence: number
  reason: string
}

export async function fetchBatchMarketRegime(
  symbols: string[],
  timeframe: string,
  timestamps: number[]
): Promise<Map<number, MarketRegimeResult>> {
  const results = new Map<number, MarketRegimeResult>()
  // Query regime for each unique timestamp
  const uniqueTimestamps = [...new Set(timestamps)]
  for (const ts of uniqueTimestamps) {
    try {
      const res = await fetch('/api/market-regime/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols,
          timeframe,
          timestamp_ms: ts,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.results && data.results.length > 0) {
          results.set(ts, data.results[0])
        }
      }
    } catch (e) {
      console.error(`Failed to fetch regime for timestamp ${ts}:`, e)
    }
  }
  return results
}

export interface MetricAnalysis {
  status: string
  symbol: string
  metric: string
  period: string
  sample_count: number
  time_range_hours: number
  warning?: string
  statistics?: {
    mean: number
    std: number
    min: number
    max: number
    abs_percentiles: { p75: number; p90: number; p95: number; p99: number }
  }
  suggestions?: {
    aggressive: { threshold: number; description: string }
    moderate: { threshold: number; description: string; recommended?: boolean }
    conservative: { threshold: number; description: string }
  }
  message?: string
}

export async function fetchMetricAnalysis(symbol: string, metric: string, period: string, exchange: string = 'hyperliquid'): Promise<MetricAnalysis> {
  const params = new URLSearchParams({ symbol, metric, period, exchange })
  const res = await fetch(`${API_BASE}/analyze?${params}`)
  if (!res.ok) throw new Error('Failed to analyze metric')
  return res.json()
}

export async function fetchFactorLibrary(): Promise<FactorItem[]> {
  const res = await fetch('/api/factors/library')
  if (!res.ok) return []
  const data = await res.json()
  return (data.factors || []).filter((f: FactorItem) =>
    f.source !== 'builtin'
  )
}

// Factor category labels for display
export const FACTOR_CATEGORY_LABELS: Record<string, string> = {
  trend: 'Trend',
  momentum: 'Momentum',
  volatility: 'Volatility',
  volume: 'Volume',
  statistical: 'Statistical',
  composite: 'Composite',
  custom: 'Custom',
}

// Constants aligned with K-line indicators (MarketFlowIndicators.tsx)
export const METRICS = [
  { value: 'oi_delta', label: 'OI Delta', desc: 'Open Interest change %. Positive=inflow, Negative=outflow' },
  { value: 'cvd', label: 'CVD', desc: 'Cumulative Volume Delta. Positive=buyers dominate, Negative=sellers dominate' },
  { value: 'funding', label: 'Funding Rate Change', desc: 'Funding rate change (aligned with K-line chart). Positive=rate increasing, Negative=rate decreasing' },
  { value: 'depth_ratio', label: 'Depth Ratio', desc: 'Bid/Ask depth ratio. >1=more bids, <1=more asks' },
  { value: 'taker_ratio', label: 'Taker Ratio', desc: 'Log taker ratio ln(buy/sell). >0=buyers, <0=sellers. Symmetric around 0' },
  { value: 'order_imbalance', label: 'Order Imbalance', desc: 'Order book imbalance (-1 to 1). Positive=buy pressure' },
  { value: 'oi', label: 'OI (Absolute)', desc: 'Absolute Open Interest value in USD' },
  { value: 'taker_volume', label: 'Taker Volume', desc: 'Composite signal: direction + ratio + volume threshold', isComposite: true },
  { value: 'macd', label: 'MACD', desc: 'MACD technical indicator events: golden cross, death cross, etc.', isEvent: true },
  { value: 'price_change', label: 'Price Change', desc: 'Price change % over time window. Formula: (current-prev)/prev*100. Positive=up, Negative=down' },
  { value: 'volatility', label: 'Volatility', desc: 'Price volatility % over time window. Formula: (high-low)/low*100. Always positive, detects swings' },
]

// Direction options for taker_volume composite signal
export const TAKER_DIRECTIONS = [
  { value: 'any', label: 'Any Direction', desc: 'Trigger on either buy or sell dominance' },
  { value: 'buy', label: 'Buy Dominant', desc: 'Only trigger when buyers dominate' },
  { value: 'sell', label: 'Sell Dominant', desc: 'Only trigger when sellers dominate' },
]

// MACD event types
export const MACD_EVENT_TYPES = [
  { value: 'golden_cross', label: 'Golden Cross', desc: 'MACD crosses above Signal line (bullish)' },
  { value: 'death_cross', label: 'Death Cross', desc: 'MACD crosses below Signal line (bearish)' },
  { value: 'histogram_positive', label: 'Histogram Positive', desc: 'Histogram turns positive (same as golden cross)' },
  { value: 'histogram_negative', label: 'Histogram Negative', desc: 'Histogram turns negative (same as death cross)' },
  { value: 'macd_above_zero', label: 'MACD Above Zero', desc: 'MACD line crosses above zero (bullish confirmation)' },
  { value: 'macd_below_zero', label: 'MACD Below Zero', desc: 'MACD line crosses below zero (bearish confirmation)' },
]

export const OPERATORS = [
  { value: 'abs_greater_than', label: '|x| > (Absolute)', desc: 'Triggers when absolute value exceeds threshold (ignores direction)' },
  { value: 'greater_than', label: '> (Greater)', desc: 'Triggers when value is greater than threshold' },
  { value: 'less_than', label: '< (Less)', desc: 'Triggers when value is less than threshold' },
  { value: 'equals', label: '= (Equals)', desc: 'Triggers when value equals threshold' },
]

export const TIME_WINDOWS = [
  { value: '1m', label: '1 min', desc: 'Very short-term, high noise' },
  { value: '3m', label: '3 min', desc: 'Short-term signals' },
  { value: '5m', label: '5 min', desc: 'Recommended for most signals' },
  { value: '15m', label: '15 min', desc: 'Medium-term, more reliable' },
  { value: '30m', label: '30 min', desc: 'Longer-term trends' },
  { value: '1h', label: '1 hour', desc: 'Major trend changes only' },
  { value: '2h', label: '2 hours', desc: 'Long-term trend confirmation' },
  { value: '4h', label: '4 hours', desc: 'Very long-term, major moves only' },
]
// Symbols are now loaded dynamically from Hyperliquid watchlist (see watchlistSymbols state)

export function formatDeps(deps: string[], t: (key: string) => string): string {
  const keyMap: [RegExp, string][] = [
    [/Signal Pool/i, 'common.dependencySignalPool'],
    [/Bound to.*Trader/i, 'common.dependencyActiveBinding'],
    [/Program Binding/i, 'common.dependencyProgramBinding'],
    [/AI Strategy/i, 'common.dependencyActiveBinding'],
    [/TriggerConfig/i, 'common.dependencyActiveBinding'],
  ]
  const messages = new Set<string>()
  for (const dep of deps) {
    const match = keyMap.find(([re]) => re.test(dep))
    messages.add(match ? t(match[1]) : dep)
  }
  return Array.from(messages).join(' ')
}
