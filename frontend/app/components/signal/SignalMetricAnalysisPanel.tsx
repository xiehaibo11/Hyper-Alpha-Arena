import type React from 'react'
import type { TFunction } from 'i18next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { MetricAnalysis } from './SignalManagerSupport'

interface SignalMetricAnalysisPanelProps {
  t: TFunction
  signalForm: any
  setSignalForm: React.Dispatch<React.SetStateAction<any>>
  metricAnalysis: MetricAnalysis | null
  analysisLoading: boolean
  analysisSymbol: string
  setAnalysisSymbol: (symbol: string) => void
  watchlistSymbols: string[]
}

export default function SignalMetricAnalysisPanel({
  t,
  signalForm,
  setSignalForm,
  metricAnalysis,
  analysisLoading,
  analysisSymbol,
  setAnalysisSymbol,
  watchlistSymbols,
}: SignalMetricAnalysisPanelProps) {
  if (signalForm.metric === 'macd' || signalForm.metric.startsWith('factor:') || signalForm.metric === '_pick_factor') {
    return null
  }

  return (
    <div className="p-3 bg-muted/50 rounded-lg border">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-medium">{t('signals.dialog.statisticalAnalysis', 'Statistical Analysis')}</span>
        <Select value={analysisSymbol} onValueChange={setAnalysisSymbol}>
          <SelectTrigger className="w-24 h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {watchlistSymbols.length > 0 ? (
              watchlistSymbols.map(sym => <SelectItem key={sym} value={sym}>{sym}</SelectItem>)
            ) : (
              <SelectItem value="BTC">BTC</SelectItem>
            )}
          </SelectContent>
        </Select>
        {watchlistSymbols.length === 0 && (
          <span className="text-xs text-muted-foreground">{t('signals.dialog.addSymbolsHint', '(Add symbols in Settings)')}</span>
        )}
      </div>
      {analysisLoading ? (
        <p className="text-xs text-muted-foreground">{t('signals.dialog.loadingAnalysis', 'Loading analysis...')}</p>
      ) : metricAnalysis?.status === 'ok' && metricAnalysis.metric === signalForm.metric ? (
        signalForm.metric === 'taker_volume' && (metricAnalysis as any).ratio_statistics ? (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Based on {metricAnalysis.sample_count} samples over {metricAnalysis.time_range_hours.toFixed(1)} hours
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-2 bg-background rounded border">
                <div className="text-xs font-medium mb-1">Ratio Multiplier</div>
                <div className="text-xs text-muted-foreground mb-2">
                  Log range: {(metricAnalysis as any).ratio_statistics?.min?.toFixed(2)} ~ {(metricAnalysis as any).ratio_statistics?.max?.toFixed(2)} (0=balanced)
                </div>
                <div className="flex flex-wrap gap-1">
                  <button type="button" onClick={() => setSignalForm(prev => ({ ...prev, ratio_threshold: (metricAnalysis as any).suggestions?.ratio?.aggressive }))} className="text-xs px-1.5 py-0.5 bg-muted border rounded hover:bg-accent">
                    {(metricAnalysis as any).suggestions?.ratio?.aggressive?.toFixed(2)}x
                  </button>
                  <button type="button" onClick={() => setSignalForm(prev => ({ ...prev, ratio_threshold: (metricAnalysis as any).suggestions?.ratio?.moderate }))} className="text-xs px-1.5 py-0.5 bg-primary/10 border border-primary rounded hover:bg-primary/20">
                    {(metricAnalysis as any).suggestions?.ratio?.moderate?.toFixed(2)}x ★
                  </button>
                  <button type="button" onClick={() => setSignalForm(prev => ({ ...prev, ratio_threshold: (metricAnalysis as any).suggestions?.ratio?.conservative }))} className="text-xs px-1.5 py-0.5 bg-muted border rounded hover:bg-accent">
                    {(metricAnalysis as any).suggestions?.ratio?.conservative?.toFixed(2)}x
                  </button>
                </div>
              </div>
              <div className="p-2 bg-background rounded border">
                <div className="text-xs font-medium mb-1">Volume (USD)</div>
                <div className="text-xs text-muted-foreground mb-2">
                  Range: {((metricAnalysis as any).volume_statistics?.min / 1000)?.toFixed(0)}K ~ {((metricAnalysis as any).volume_statistics?.max / 1000)?.toFixed(0)}K
                </div>
                <div className="flex flex-wrap gap-1">
                  <button type="button" onClick={() => setSignalForm(prev => ({ ...prev, volume_threshold: (metricAnalysis as any).suggestions?.volume?.low }))} className="text-xs px-1.5 py-0.5 bg-muted border rounded hover:bg-accent">
                    {((metricAnalysis as any).suggestions?.volume?.low / 1000)?.toFixed(0)}K
                  </button>
                  <button type="button" onClick={() => setSignalForm(prev => ({ ...prev, volume_threshold: (metricAnalysis as any).suggestions?.volume?.medium }))} className="text-xs px-1.5 py-0.5 bg-primary/10 border border-primary rounded hover:bg-primary/20">
                    {((metricAnalysis as any).suggestions?.volume?.medium / 1000)?.toFixed(0)}K ★
                  </button>
                  <button type="button" onClick={() => setSignalForm(prev => ({ ...prev, volume_threshold: (metricAnalysis as any).suggestions?.volume?.high }))} className="text-xs px-1.5 py-0.5 bg-muted border rounded hover:bg-accent">
                    {((metricAnalysis as any).suggestions?.volume?.high / 1000)?.toFixed(0)}K
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : metricAnalysis.suggestions ? (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Based on {metricAnalysis.sample_count} samples over {metricAnalysis.time_range_hours.toFixed(1)} hours
            </p>
            {metricAnalysis.warning && (
              <p className="text-xs text-yellow-600">{metricAnalysis.warning}</p>
            )}
            <div className="text-xs">
              <span className="text-muted-foreground">Range: </span>
              {signalForm.metric === 'funding'
                ? `${metricAnalysis.statistics?.min.toFixed(1)} ~ ${metricAnalysis.statistics?.max.toFixed(1)}`
                : `${metricAnalysis.statistics?.min.toFixed(4)} ~ ${metricAnalysis.statistics?.max.toFixed(4)}`
              }
            </div>
            <div className="text-xs font-medium mt-2">{t('signals.dialog.suggestedThresholds', 'Suggested thresholds:')}</div>
            <div className="flex flex-wrap gap-2 mt-1">
              {(['aggressive', 'moderate', 'conservative'] as const).map(kind => {
                const suggestion = metricAnalysis.suggestions![kind]
                const isModerate = kind === 'moderate'
                return (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => setSignalForm(prev => ({ ...prev, threshold: suggestion.threshold }))}
                    className={`text-xs px-2 py-1 border rounded hover:bg-accent ${isModerate ? 'bg-primary/10 border-primary hover:bg-primary/20' : 'bg-background'}`}
                    title={suggestion.description}
                  >
                    {t(`signals.dialog.${kind}`, kind[0].toUpperCase() + kind.slice(1))} {signalForm.metric === 'funding'
                      ? suggestion.threshold.toFixed(1)
                      : suggestion.threshold.toFixed(4)}
                    {(suggestion as any).multiplier && ` (${(suggestion as any).multiplier}x)`}{isModerate ? ' ★' : ''}
                  </button>
                )
              })}
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">{t('signals.dialog.analysisDataMismatch', 'Analysis data format mismatch. Please reselect metric.')}</p>
        )
      ) : metricAnalysis?.status === 'insufficient_data' ? (
        <p className="text-xs text-yellow-600">{metricAnalysis.message}</p>
      ) : (
        <p className="text-xs text-muted-foreground">{t('signals.dialog.unableToLoadAnalysis', 'Unable to load analysis')}</p>
      )}
    </div>
  )
}
