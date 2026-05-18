import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import PacmanLoader from '../ui/pacman-loader'
import TradingViewChart from './TradingViewChart'

type Exchange = 'hyperliquid' | 'binance'
type ChartType = 'candlestick' | 'line' | 'area'

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
        />
      </CardContent>
    </Card>
  )
}
