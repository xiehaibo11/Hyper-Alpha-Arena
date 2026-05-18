import { useTranslation } from 'react-i18next'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select'

type Exchange = 'hyperliquid' | 'binance' | 'okx'

interface KlineMobileSelectorProps {
  selectedExchange: Exchange
  onExchangeChange: (exchange: Exchange) => void
  selectedSymbol: string
  onSymbolChange: (symbol: string) => void
  selectedPeriod: string
  onPeriodChange: (period: string) => void
  watchlistSymbols: string[]
}

export default function KlineMobileSelector({
  selectedExchange,
  onExchangeChange,
  selectedSymbol,
  onSymbolChange,
  selectedPeriod,
  onPeriodChange,
  watchlistSymbols,
}: KlineMobileSelectorProps) {
  const { t } = useTranslation()

  return (
    <div className="md:hidden flex items-center gap-2 px-2 py-2 bg-background border-b">
      <div className="flex items-center gap-0.5 p-0.5 rounded border-2 border-amber-500/70 bg-amber-500/5">
        <button
          onClick={() => onExchangeChange('hyperliquid')}
          className={`p-1.5 rounded transition-all ${selectedExchange === 'hyperliquid' ? 'bg-primary text-primary-foreground' : ''}`}
        >
          <svg width="14" height="14" viewBox="0 0 144 144" fill="none">
            <path d="M144 71.6991C144 119.306 114.866 134.582 99.5156 120.98C86.8804 109.889 83.1211 86.4521 64.116 84.0456C39.9942 81.0113 37.9057 113.133 22.0334 113.133C3.5504 113.133 0 86.2428 0 72.4315C0 58.3063 3.96809 39.0542 19.736 39.0542C38.1146 39.0542 39.1588 66.5722 62.132 65.1073C85.0007 63.5379 85.4184 34.8689 100.247 22.6271C113.195 12.0593 144 23.4641 144 71.6991Z" fill={selectedExchange === 'hyperliquid' ? 'currentColor' : '#50E3C2'} />
          </svg>
        </button>
        <button
          onClick={() => onExchangeChange('binance')}
          className={`p-1.5 rounded transition-all ${selectedExchange === 'binance' ? 'bg-primary text-primary-foreground' : ''}`}
        >
          <img src="/static/binance_logo.svg" alt="Binance" width={14} height={14} />
        </button>
        <button
          onClick={() => onExchangeChange('okx')}
          className={`p-1.5 rounded transition-all ${selectedExchange === 'okx' ? 'bg-primary text-primary-foreground' : ''}`}
        >
          <img src="/static/okx_logo.svg" alt="OKX" width={14} height={14} />
        </button>
      </div>
      <Select value={selectedSymbol} onValueChange={onSymbolChange}>
        <SelectTrigger className="flex-1 h-9">
          <SelectValue placeholder={t('kline.selectSymbol', 'Select Symbol')} />
        </SelectTrigger>
        <SelectContent>
          {watchlistSymbols.map(symbol => (
            <SelectItem key={symbol} value={symbol}>{symbol}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={selectedPeriod} onValueChange={onPeriodChange}>
        <SelectTrigger className="w-20 h-9">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {['1m', '5m', '15m', '1h', '4h', '1d'].map(period => (
            <SelectItem key={period} value={period}>{period}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
