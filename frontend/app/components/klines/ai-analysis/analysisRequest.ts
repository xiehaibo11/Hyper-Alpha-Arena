import type { ExchangeType } from '../../hyperliquid/WalletSelector'
import type { AnalysisResult, PositionItem } from './types'

interface BuildRequestArgs {
  accountId: string
  symbol: string
  period: string
  exchange: ExchangeType
  klineLimit: number
  klines: any[]
  indicators: Record<string, any>
  marketData: any
  positions: PositionItem[]
  selectedFlowIndicators: string[]
  userMessage: string
}

interface RecoverArgs {
  symbol: string
  period: string
  requestStartTime: Date
  attempts?: number
  delayMs?: number
}

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

function parseServerTimestamp(value: string) {
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(value)
  const normalized = value.replace(/(\.\d{3})\d+/, '$1')
  return new Date(hasTimezone ? normalized : `${normalized}Z`).getTime()
}

function computeMA(data: any[], period: number) {
  if (!data || data.length < period) return []
  const closes = data.map((k) => Number(k.close || k.c))
  const ma: number[] = []

  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1)
    const avg = slice.reduce((a, b) => a + b, 0) / period
    ma.push(Number.isFinite(avg) ? Number(avg.toFixed(4)) : 0)
  }

  return Array(period - 1).fill(null).concat(ma)
}

export function buildKlineAnalysisRequest(args: BuildRequestArgs) {
  const slicedKlines = args.klines.slice(-args.klineLimit)
  const marketDataPayload = {
    price: args.marketData?.price || 0,
    oracle_price: args.marketData?.oracle_price || 0,
    change24h: args.marketData?.change24h || 0,
    volume24h: args.marketData?.volume24h || 0,
    percentage24h: args.marketData?.percentage24h || 0,
    open_interest: args.marketData?.open_interest || 0,
    funding_rate: args.marketData?.funding_rate || 0
  }
  const positionPayload = args.positions.map((p) => ({
    symbol: p.symbol,
    size: p.size,
    entry_price: p.entry_price,
    mark_price: p.mark_price,
    position_value: p.position_value,
    liquidation_price: p.liquidation_price,
    side: p.side,
    leverage: p.leverage,
    unrealized_pnl: p.unrealized_pnl,
    pnl_percentage: p.pnl_percentage,
  }))

  return {
    account_id: parseInt(args.accountId),
    symbol: args.symbol,
    period: args.period,
    kline_limit: args.klineLimit,
    klines: slicedKlines.map(k => ({
      time: k.time,
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
      volume: k.volume || 0
    })),
    indicators: {
      ...args.indicators,
      ...(args.indicators?.MA5?.length ? {} : { MA5: computeMA(slicedKlines, 5) }),
      ...(args.indicators?.MA10?.length ? {} : { MA10: computeMA(slicedKlines, 10) }),
      ...(args.indicators?.MA20?.length ? {} : { MA20: computeMA(slicedKlines, 20) }),
    },
    market_data: marketDataPayload,
    positions: positionPayload,
    selected_flow_indicators: args.selectedFlowIndicators,
    exchange: args.exchange,
    user_message: args.userMessage.trim() || null,
    prompt_snapshot: JSON.stringify({
      symbol: args.symbol,
      period: args.period,
      exchange: args.exchange,
      kline_limit: args.klineLimit,
      indicators: Object.keys(args.indicators || {}),
      flow_indicators: args.selectedFlowIndicators,
      positions: positionPayload,
      market_data: marketDataPayload,
      user_message: args.userMessage.trim() || null
    }, null, 2)
  }
}

export async function parseAnalysisResponse(response: Response): Promise<AnalysisResult> {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data?.error || `AI analysis failed (${response.status})`)
    }
    return data
  }

  if (!response.ok) {
    throw new Error(`AI analysis gateway returned ${response.status}`)
  }

  throw new Error('AI analysis returned a non-JSON response')
}

export async function recoverRecentAnalysisResult({
  symbol,
  period,
  requestStartTime,
  attempts = 12,
  delayMs = 3000,
}: RecoverArgs): Promise<AnalysisResult | null> {
  const earliest = requestStartTime.getTime() - 15000
  const latest = requestStartTime.getTime() + 15 * 60 * 1000

  for (let attempt = 0; attempt < attempts; attempt++) {
    if (attempt > 0) await delay(delayMs)

    const response = await fetch(
      `/api/klines/ai-analysis/history?symbol=${encodeURIComponent(symbol)}&limit=10`,
      { cache: 'no-store' }
    )
    if (!response.ok) continue

    const data = await response.json()
    const matched = (data.history || []).find((item: any) => {
      const createdAt = parseServerTimestamp(item.created_at)
      return item.symbol === symbol && item.period === period && createdAt >= earliest && createdAt <= latest
    })

    if (matched) {
      return {
        success: true,
        analysis_id: matched.id,
        symbol: matched.symbol,
        period: matched.period,
        model: matched.model_used,
        analysis: matched.analysis,
        created_at: matched.created_at
      }
    }
  }

  return null
}

export function getAnalysisErrorMessage(error: any) {
  if (error?.name === 'AbortError') {
    return 'Analysis timeout (10 minutes). Please try again with fewer K-lines or a simpler question.'
  }

  const message = String(error?.message || '')
  if (message.includes('gateway returned 504')) {
    return 'Analysis gateway timed out before the saved result could be retrieved. Please try again.'
  }
  if (message.includes('non-JSON') || message.includes('Unexpected token')) {
    return 'Analysis returned an invalid gateway response. Please try again.'
  }

  return message || 'Network error occurred'
}
