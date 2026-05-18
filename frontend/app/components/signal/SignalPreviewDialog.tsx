import type { TFunction } from 'i18next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import PacmanLoader from '../ui/pacman-loader'
import SignalPreviewChart from './SignalPreviewChart'
import { ExchangeBadge, type SignalDefinition, type SignalPool } from './SignalManagerSupport'

interface SignalPreviewDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  previewPool: SignalPool | null
  previewSignal: SignalDefinition | null
  previewLoading: boolean
  previewData: any
  regimeLoading: boolean
  chartTimeframe: string
  watchlistSymbols: string[]
  previewSymbol: string
  t: TFunction
  onCheckMarketRegime: () => void
  onRefreshWithTimeframe: (timeframe: string) => void
  onOpenPoolPreview: (pool: SignalPool, symbol: string) => void
  onOpenSignalPreview: (signal: SignalDefinition, symbol: string) => void
}

export default function SignalPreviewDialog({
  open,
  onOpenChange,
  previewPool,
  previewSignal,
  previewLoading,
  previewData,
  regimeLoading,
  chartTimeframe,
  watchlistSymbols,
  previewSymbol,
  t,
  onCheckMarketRegime,
  onRefreshWithTimeframe,
  onOpenPoolPreview,
  onOpenSignalPreview,
}: SignalPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[1200px] max-w-[95vw] h-[860px] max-h-[95vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <span>{previewPool ? t('signals.preview.poolPreview', { name: previewPool.pool_name, defaultValue: `Pool Preview: ${previewPool.pool_name}` }) : t('signals.preview.signalPreview', { name: previewSignal?.signal_name, defaultValue: `Signal Preview: ${previewSignal?.signal_name}` })}</span>
            <ExchangeBadge exchange={previewPool?.exchange || previewSignal?.exchange || 'hyperliquid'} />
          </DialogTitle>
          <DialogDescription>
            {previewPool
              ? t('signals.preview.poolBacktestDesc', { logic: previewPool.logic || 'OR', defaultValue: `Historical backtest showing combined triggers (${previewPool.logic || 'OR'} logic)` })
              : t('signals.preview.signalBacktestDesc', 'Historical backtest showing where this signal would have triggered')}
          </DialogDescription>
        </DialogHeader>

        {previewLoading ? (
          <div className="flex items-center justify-center h-[500px] gap-3">
            <PacmanLoader className="w-16 h-8" />
            <span className="text-muted-foreground">{t('signals.preview.loadingPreview', 'Loading preview data...')}</span>
          </div>
        ) : previewData?.error ? (
          <div className="flex items-center justify-center h-[500px]">
            <div className="text-center text-destructive">
              <p className="font-medium">{t('signals.preview.previewError', 'Preview Error')}</p>
              <p className="text-sm mt-2">{previewData.error}</p>
            </div>
          </div>
        ) : previewData?.klines ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div className="bg-muted p-3 rounded">
                <div className="text-muted-foreground">{t('signals.preview.symbol', 'Symbol')}</div>
                <div className="font-medium">{previewData.symbol}</div>
              </div>
              <div className="bg-muted p-3 rounded">
                <div className="text-muted-foreground">{t('signals.preview.timeWindow', 'Time Window')}</div>
                <div className="font-medium">{previewData.time_window}</div>
              </div>
              <div className="bg-muted p-3 rounded">
                <div className="text-muted-foreground">{t('signals.preview.klines', 'K-lines')}</div>
                <div className="font-medium">{previewData.kline_count}</div>
              </div>
              <div className="bg-muted p-3 rounded">
                <div className="text-muted-foreground">{t('signals.preview.triggers', 'Triggers')}</div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-yellow-500">{previewData.trigger_count}</span>
                  {previewData.trigger_count > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-6 text-xs px-2"
                      disabled={regimeLoading}
                      onClick={onCheckMarketRegime}
                    >
                      {regimeLoading ? t('signals.preview.checking', 'Checking...') : t('signals.preview.checkRegime', 'Check Regime')}
                    </Button>
                  )}
                </div>
              </div>
            </div>

            <div className="bg-muted p-3 rounded text-sm">
              {previewData.isPoolPreview ? (
                <div className="space-y-1">
                  <div>
                    <span className="text-muted-foreground">{t('signals.preview.logic', 'Logic')}: </span>
                    <span className={`px-2 py-0.5 rounded ${previewData.logic === 'AND' ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'}`}>
                      {previewData.logic || 'OR'}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t('signals.preview.signals', 'Signals')}: </span>
                    <span className="font-mono">
                      {Object.values(previewData.signal_names || {}).join(', ')}
                    </span>
                  </div>
                </div>
              ) : (
                <>
                  <span className="text-muted-foreground">{t('signals.preview.condition', 'Condition')}: </span>
                  <span className="font-mono">
                    {previewData.condition?.metric} {previewData.condition?.operator} {previewData.condition?.threshold}
                  </span>
                </>
              )}
            </div>

            <div className="border rounded-lg overflow-hidden">
              <SignalPreviewChart
                klines={previewData.klines}
                triggers={previewData.triggers || []}
                timeWindow={chartTimeframe}
                macd={previewData.macd}
              />
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-muted-foreground">{t('signals.preview.chartTimeframe', 'Chart timeframe:')}</span>
              {['1m', '3m', '5m', '15m', '30m', '1h', '4h'].map(tf => (
                <Button
                  key={tf}
                  variant={chartTimeframe === tf ? 'default' : 'outline'}
                  size="sm"
                  disabled={previewLoading}
                  onClick={() => onRefreshWithTimeframe(tf)}
                >
                  {tf}
                </Button>
              ))}
              <span className="text-xs text-muted-foreground ml-2">
                ({t('signals.preview.signal', 'Signal')}: {previewData.time_window || '5m'})
              </span>
              <span className="text-xs text-yellow-500 ml-2">
                {t('signals.preview.largerTimeframeNote', 'Note: Larger timeframes require longer calculation time')}
              </span>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-muted-foreground">{t('signals.preview.changeSymbol', 'Change symbol:')}</span>
              {watchlistSymbols.length > 0 ? (
                watchlistSymbols.map(sym => (
                  <Button
                    key={sym}
                    variant={previewSymbol === sym ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => {
                      if (previewPool) {
                        onOpenPoolPreview(previewPool, sym)
                      } else if (previewSignal) {
                        onOpenSignalPreview(previewSignal, sym)
                      }
                    }}
                  >
                    {sym}
                  </Button>
                ))
              ) : (
                <span className="text-sm text-muted-foreground italic">No symbols in Watchlist</span>
              )}
              <span className="text-xs text-muted-foreground ml-2">
                (Manage symbols in Settings page)
              </span>
            </div>
          </div>
        ) : (
          <div className="text-center text-muted-foreground py-8">
            No data available
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
