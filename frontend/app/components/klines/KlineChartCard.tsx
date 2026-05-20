import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import PacmanLoader from '../ui/pacman-loader'
import TradingViewChart from './TradingViewChart'

type Exchange = 'hyperliquid' | 'binance' | 'okx'
type ChartType = 'candlestick' | 'line' | 'area'

const getRefreshIntervalMs = (exchange: Exchange, period: string) => {
  const binanceIntervals: Record<string, number> = {
    '1m': 15000,
    '3m': 15000,
    '5m': 20000,
    '15m': 30000,
    '30m': 45000,
    '1h': 60000,
    '2h': 60000,
    '4h': 90000,
    '8h': 120000,
    '12h': 120000,
    '1d': 120000,
    '3d': 120000,
    '1w': 120000,
    '1M': 120000,
  }

  const defaultIntervals: Record<string, number> = {
    '1m': 12000,
    '3m': 12000,
    '5m': 15000,
    '15m': 20000,
    '30m': 30000,
    '1h': 45000,
    '2h': 60000,
    '4h': 60000,
    '8h': 90000,
    '12h': 90000,
    '1d': 120000,
    '3d': 120000,
    '1w': 120000,
    '1M': 120000,
  }

  const intervals = exchange === 'binance' ? binanceIntervals : defaultIntervals
  return intervals[period] ?? 120000
}

interface KlineChartCardProps {
  selectedSymbol: string
  selectedPeriod: string
  selectedExchange: Exchange
  chartType: ChartType
  selectedIndicators: string[]
  selectedFlowIndicators: string[]
  chartLoading: boolean
  onChartTypeChange: (chartType: ChartType) => void
  onLoadingChange: (loading: boolean) => void
  onIndicatorLoadingChange: (loading: boolean) => void
  onDataUpdate: (klines: any[], indicators: Record<string, any>) => void
}

export default function KlineChartCard({
  selectedSymbol,
  selectedPeriod,
  selectedExchange,
  chartType,
  selectedIndicators,
  selectedFlowIndicators,
  chartLoading,
  onChartTypeChange,
  onLoadingChange,
  onIndicatorLoadingChange,
  onDataUpdate,
}: KlineChartCardProps) {
  const { t } = useTranslation()
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    if (!selectedSymbol || !selectedPeriod) return

    const intervalMs = getRefreshIntervalMs(selectedExchange, selectedPeriod)
    const timer = window.setInterval(() => {
      if (document.hidden) return
      setRefreshToken(value => value + 1)
    }, intervalMs)

    return () => window.clearInterval(timer)
  }, [selectedExchange, selectedPeriod, selectedSymbol])

  return (
    <Card className="flex-1 min-h-[300px] md:min-h-[420px] min-w-0 overflow-hidden">
      <CardHeader className="py-2 md:py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 md:gap-3">
            <CardTitle className="text-xs md:text-sm">
              {selectedSymbol} ({selectedPeriod})
            </CardTitle>
            {chartLoading && (
              <div className="hidden md:flex items-center gap-2 text-sm text-muted-foreground">
                <PacmanLoader className="w-12 h-6" />
                {t('kline.loadingKlineData', 'Loading K-line data...')}
              </div>
            )}
          </div>
          <div className="hidden md:flex gap-1 bg-background/80 backdrop-blur-sm rounded-md p-1 border">
            {[
              ['candlestick', t('kline.candlestick', 'Candlestick')],
              ['line', t('kline.line', 'Line')],
              ['area', t('kline.area', 'Area')],
            ].map(([value, label]) => (
              <button
                key={value}
                onClick={() => onChartTypeChange(value as ChartType)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  chartType === value ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="h-[calc(100%-3rem)] pb-4">
        <TradingViewChart
          symbol={selectedSymbol}
          period={selectedPeriod}
          exchange={selectedExchange}
          chartType={chartType}
          selectedIndicators={selectedIndicators}
          selectedFlowIndicators={selectedFlowIndicators}
          onLoadingChange={onLoadingChange}
          onIndicatorLoadingChange={onIndicatorLoadingChange}
          onDataUpdate={onDataUpdate}
          incrementalRefreshToken={refreshToken}
        />
      </CardContent>
    </Card>
  )
}
