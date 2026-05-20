import { AreaSeries, CandlestickSeries, LineSeries } from 'lightweight-charts'

export type ChartType = 'candlestick' | 'line' | 'area'

export interface TradingViewChartProps {
  symbol: string
  period: string
  exchange?: 'hyperliquid' | 'binance' | 'okx'
  chartType: ChartType
  selectedIndicators: string[]
  selectedFlowIndicators?: string[]
  onLoadingChange: (loading: boolean) => void
  data?: any[]
  onLoadMore?: () => void
  onDataUpdate?: (klines: any[], indicators: any) => void
  onIndicatorLoadingChange?: (loading: boolean) => void
  showVolumePane?: boolean
  eventMarkers?: Array<{
    id?: string
    kind?: 'news' | 'flow'
    time: number
    position: 'aboveBar' | 'belowBar'
    color: string
    shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
    text?: string
    title?: string
    summary?: string
    tone?: 'bullish' | 'bearish' | 'mixed'
    metadata?: string[]
    iconVariant?: 'news' | 'flow-up' | 'flow-down'
  }>
  activeEventMarkerId?: string
  onEventMarkerClick?: (eventId: string) => void
  incrementalRefreshToken?: number
}

export const FLOW_COLORS: Record<string, { up: string; down: string; line: string }> = {
  cvd: { up: '#22c55e', down: '#ef4444', line: '#3b82f6' },
  taker_volume: { up: '#22c55e', down: '#ef4444', line: '#3b82f6' },
  oi: { up: '#22c55e', down: '#ef4444', line: '#8b5cf6' },
  oi_delta: { up: '#22c55e', down: '#ef4444', line: '#8b5cf6' },
  funding: { up: '#22c55e', down: '#ef4444', line: '#f59e0b' },
  depth_ratio: { up: '#22c55e', down: '#ef4444', line: '#06b6d4' },
  order_imbalance: { up: '#22c55e', down: '#ef4444', line: '#ec4899' }
}

export const FLOW_LABELS: Record<string, string> = {
  cvd: 'CVD',
  taker_volume: 'Taker Volume',
  oi: 'Open Interest',
  oi_delta: 'OI Delta',
  funding: 'Funding Rate (bps)',
  depth_ratio: 'Depth Ratio (log)',
  order_imbalance: 'Order Imbalance'
}

export const isMobileDevice = () => typeof window !== 'undefined' && window.innerWidth < 768

export const formatMobilePrice = (price: number): string => {
  if (price >= 1000000) {
    return (price / 1000000).toFixed(2) + 'M'
  }
  if (price >= 10000) {
    return (price / 1000).toFixed(1) + 'K'
  }
  if (price >= 1000) {
    return (price / 1000).toFixed(2) + 'K'
  }
  if (price >= 1) {
    return price.toFixed(2)
  }
  if (price >= 0.01) {
    return price.toFixed(4)
  }
  return price.toFixed(6)
}

export function getMarkerParticleColor(marker: { tone?: 'bullish' | 'bearish' | 'mixed'; iconVariant?: 'news' | 'flow-up' | 'flow-down' }) {
  if (marker.tone === 'bullish' || marker.iconVariant === 'flow-up') return '#00e676'
  if (marker.tone === 'bearish' || marker.iconVariant === 'flow-down') return '#ff5252'
  return '#00d4ff'
}

export const needsChartReinit = (prevIndicators: string[], newIndicators: string[]) => {
  const subplotIndicators = ['RSI14', 'RSI7', 'MACD', 'ATR14', 'STOCH', 'OBV']
  const prevSubplots = prevIndicators.filter(ind => subplotIndicators.includes(ind))
  const newSubplots = newIndicators.filter(ind => subplotIndicators.includes(ind))

  return (prevSubplots.length === 0) !== (newSubplots.length === 0)
}

export const createPaneLabel = (text: string) => ({
  paneViews() {
    return [{
      renderer() {
        return {
          draw(target: any) {
            target.useMediaCoordinateSpace((scope: any) => {
              const ctx = scope.context
              ctx.font = '12px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
              ctx.fillStyle = 'rgba(156, 163, 175, 0.6)'
              ctx.textAlign = 'left'
              ctx.textBaseline = 'top'
              ctx.fillText(text, 8, 8)
            })
          }
        }
      }
    }]
  }
})

export const createMainSeries = (chart: any, type: ChartType) => {
  switch (type) {
    case 'candlestick':
      return chart.addSeries(CandlestickSeries, {
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderDownColor: '#ef4444',
        borderUpColor: '#22c55e',
        wickDownColor: '#ef4444',
        wickUpColor: '#22c55e',
      })
    case 'line':
      return chart.addSeries(LineSeries, {
        color: '#3b82f6',
        lineWidth: 2,
      })
    case 'area':
      return chart.addSeries(AreaSeries, {
        topColor: '#3b82f640',
        bottomColor: '#3b82f610',
        lineColor: '#3b82f6',
        lineWidth: 2,
      })
    default:
      return chart.addSeries(CandlestickSeries, {
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderDownColor: '#ef4444',
        borderUpColor: '#22c55e',
        wickDownColor: '#ef4444',
        wickUpColor: '#22c55e',
      })
  }
}

export const convertDataForSeries = (data: any[], type: ChartType) => {
  switch (type) {
    case 'candlestick':
      return data.map(item => ({
        time: item.time,
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close,
      }))
    case 'line':
    case 'area':
      return data.map(item => ({
        time: item.time,
        value: item.close,
      }))
    default:
      return data
  }
}

export const calculateMA = (data: any[], period: number) => {
  const result = []
  for (let i = period - 1; i < data.length; i++) {
    const sum = data.slice(i - period + 1, i + 1).reduce((acc, item) => acc + item.close, 0)
    result.push({
      time: data[i].time,
      value: sum / period,
    })
  }
  return result
}
