import type { Dispatch, SetStateAction } from 'react'
import type { TFunction } from 'i18next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Activity, FlaskConical } from 'lucide-react'
import SignalMetricAnalysisPanel from './SignalMetricAnalysisPanel'
import {
  BinanceLogo,
  FACTOR_CATEGORY_LABELS,
  HyperliquidLogo,
  MACD_EVENT_TYPES,
  METRICS,
  OPERATORS,
  TAKER_DIRECTIONS,
  TIME_WINDOWS,
  type FactorItem,
  type MetricAnalysis,
  type SignalDefinition,
} from './SignalManagerSupport'

export interface SignalFormState {
  signal_name: string
  description: string
  metric: string
  operator: string
  threshold: number
  time_window: string
  enabled: boolean
  exchange: string
  direction: string
  ratio_threshold: number
  volume_threshold: number
  event_types: string[]
}

interface SignalDefinitionDialogProps {
  open: boolean
  editingSignal: SignalDefinition | null
  signalForm: SignalFormState
  setSignalForm: Dispatch<SetStateAction<SignalFormState>>
  factorLibrary: FactorItem[]
  factorCategory: string
  factorSearch: string
  metricAnalysis: MetricAnalysis | null
  analysisLoading: boolean
  analysisSymbol: string
  watchlistSymbols: string[]
  savingSignal: boolean
  t: TFunction
  onOpenChange: (open: boolean) => void
  onSave: () => void
  setFactorCategory: (category: string) => void
  setFactorSearch: (search: string) => void
  setAnalysisSymbol: (symbol: string) => void
}

export default function SignalDefinitionDialog({
  open,
  editingSignal,
  signalForm,
  setSignalForm,
  factorLibrary,
  factorCategory,
  factorSearch,
  metricAnalysis,
  analysisLoading,
  analysisSymbol,
  watchlistSymbols,
  savingSignal,
  t,
  onOpenChange,
  onSave,
  setFactorCategory,
  setFactorSearch,
  setAnalysisSymbol,
}: SignalDefinitionDialogProps) {
  const isFactorMode = signalForm.metric.startsWith('factor:') || signalForm.metric === '_pick_factor'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={isFactorMode ? 'max-w-[960px]' : 'max-w-lg'}>
        <DialogHeader>
          <DialogTitle>{editingSignal ? t('signals.dialog.editSignal', 'Edit Signal') : t('signals.dialog.newSignal', 'New Signal')}</DialogTitle>
          <DialogDescription>{t('signals.dialog.configureSignal', 'Configure when this signal should trigger')}</DialogDescription>
        </DialogHeader>
        <div className={isFactorMode ? 'grid grid-cols-[340px_1fr] gap-6' : ''}>
          <div className="space-y-4">
            <div>
              <Label>{t('signals.dialog.signalNameLabel', 'Signal Name')}</Label>
              <Input
                value={signalForm.signal_name}
                onChange={e => setSignalForm(prev => ({ ...prev, signal_name: e.target.value }))}
                placeholder={t('signals.dialog.signalNamePlaceholder', 'e.g., OI Surge Signal')}
              />
            </div>
            <div>
              <Label>{t('signals.dialog.descriptionLabel', 'Description')}</Label>
              <Input
                value={signalForm.description}
                onChange={e => setSignalForm(prev => ({ ...prev, description: e.target.value }))}
                placeholder={t('signals.dialog.descriptionPlaceholder', 'What market condition does this signal detect?')}
              />
            </div>
            <div>
              <Label>{t('signals.dialog.exchangeLabel', 'Exchange')}</Label>
              <Select value={signalForm.exchange} onValueChange={v => setSignalForm(prev => ({ ...prev, exchange: v }))}>
                <SelectTrigger>
                  <SelectValue>
                    <span className="flex items-center gap-2">
                      {signalForm.exchange === 'hyperliquid' ? <HyperliquidLogo /> : <BinanceLogo />}
                      {signalForm.exchange === 'hyperliquid' ? 'Hyperliquid' : 'Binance'}
                    </span>
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="hyperliquid">
                    <span className="flex items-center gap-2"><HyperliquidLogo />Hyperliquid</span>
                  </SelectItem>
                  <SelectItem value="binance">
                    <span className="flex items-center gap-2"><BinanceLogo />Binance</span>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>{t('signals.dialog.metricLabel', 'Metric')}</Label>
              <Select
                value={signalForm.metric === '_pick_factor' ? '_pick_factor' : signalForm.metric}
                onValueChange={v => {
                  if (v === '_pick_factor') {
                    setSignalForm(prev => ({ ...prev, metric: '_pick_factor' }))
                  } else {
                    setSignalForm(prev => ({ ...prev, metric: v }))
                    setFactorSearch('')
                    setFactorCategory('all')
                  }
                }}
              >
                <SelectTrigger>
                  <SelectValue>
                    {signalForm.metric.startsWith('factor:')
                      ? <span className="flex items-center gap-1.5"><FlaskConical className="w-3.5 h-3.5 text-[#B8860B]" />{signalForm.metric.split(':')[1]}</span>
                      : signalForm.metric === '_pick_factor'
                        ? <span className="flex items-center gap-1.5 text-[#B8860B]"><FlaskConical className="w-3.5 h-3.5" />{t('signals.dialog.selectFactor', 'Select factor ->')}</span>
                        : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <div className="px-2 py-1 text-xs font-semibold text-muted-foreground flex items-center gap-1.5"><Activity className="w-3.5 h-3.5" />{t('signals.dialog.marketFlowMetrics', 'Market Flow')}</div>
                  {METRICS.map(m => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}
                  {factorLibrary.length > 0 && (
                    <SelectItem value="_pick_factor">
                      <span className="flex items-center gap-1.5 text-[#B8860B]">
                        <FlaskConical className="w-3.5 h-3.5" />
                        {t('signals.dialog.factorMetrics', 'Factor Library')} ({factorLibrary.length})
                      </span>
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground mt-1">
                {signalForm.metric.startsWith('factor:')
                  ? factorLibrary.find(f => f.name === signalForm.metric.split(':')[1])?.description || signalForm.metric
                  : signalForm.metric === '_pick_factor'
                    ? t('signals.dialog.pickFactorHint', 'Browse and select a factor from the panel on the right')
                    : METRICS.find(m => m.value === signalForm.metric)?.desc}
              </p>
            </div>
            {signalForm.metric === 'taker_volume' ? (
              <div className="space-y-4 p-3 bg-blue-500/10 rounded-lg border border-blue-500/30">
                <div className="text-xs font-medium text-blue-400">{t('signals.dialog.compositeConfig', 'Composite Signal Configuration')}</div>
                <div>
                  <Label>{t('signals.dialog.directionLabel', 'Direction')}</Label>
                  <Select value={signalForm.direction} onValueChange={v => setSignalForm(prev => ({ ...prev, direction: v }))}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {TAKER_DIRECTIONS.map(d => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    {TAKER_DIRECTIONS.find(d => d.value === signalForm.direction)?.desc}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>{t('signals.dialog.ratioThreshold', 'Ratio Threshold')}</Label>
                    <Input
                      type="number"
                      step="0.1"
                      min="1.01"
                      value={signalForm.ratio_threshold}
                      onChange={e => setSignalForm(prev => ({ ...prev, ratio_threshold: parseFloat(e.target.value) || 1.5 }))}
                    />
                    <p className="text-xs text-muted-foreground mt-1">{t('signals.dialog.ratioThresholdDesc', 'Multiplier (e.g., 1.5 = 50% more). Symmetric for buy/sell.')}</p>
                  </div>
                  <div>
                    <Label>{t('signals.dialog.volumeThreshold', 'Volume Threshold')}</Label>
                    <Input
                      type="number"
                      step="1000"
                      min="0"
                      value={signalForm.volume_threshold}
                      onChange={e => setSignalForm(prev => ({ ...prev, volume_threshold: parseFloat(e.target.value) || 0 }))}
                    />
                    <p className="text-xs text-muted-foreground mt-1">{t('signals.dialog.volumeThresholdDesc', 'Min volume (USD)')}</p>
                  </div>
                </div>
              </div>
            ) : signalForm.metric === 'macd' ? (
              <div className="space-y-4 p-3 bg-purple-500/10 rounded-lg border border-purple-500/30">
                <div className="text-xs font-medium text-purple-400">{t('signals.dialog.macdConfig', 'MACD Event Configuration')}</div>
                <div>
                  <Label>{t('signals.dialog.eventTypes', 'Event Types (select one or more)')}</Label>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    {MACD_EVENT_TYPES.map(evt => (
                      <label key={evt.value} className="flex items-center gap-2 p-2 rounded border cursor-pointer hover:bg-accent">
                        <input
                          type="checkbox"
                          checked={signalForm.event_types.includes(evt.value)}
                          onChange={e => {
                            if (e.target.checked) {
                              setSignalForm(prev => ({ ...prev, event_types: [...prev.event_types, evt.value] }))
                            } else {
                              setSignalForm(prev => ({ ...prev, event_types: prev.event_types.filter(v => v !== evt.value) }))
                            }
                          }}
                          className="rounded"
                        />
                        <div>
                          <div className="text-sm font-medium">{evt.label}</div>
                          <div className="text-xs text-muted-foreground">{evt.desc}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                  {signalForm.event_types.length === 0 && (
                    <p className="text-xs text-red-500 mt-1">{t('signals.dialog.selectAtLeastOne', 'Please select at least one event type')}</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>{t('signals.dialog.operatorLabel', 'Operator')}</Label>
                  <Select value={signalForm.operator} onValueChange={v => setSignalForm(prev => ({ ...prev, operator: v }))}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {OPERATORS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    {OPERATORS.find(o => o.value === signalForm.operator)?.desc}
                  </p>
                </div>
                <div>
                  <Label>{t('signals.dialog.thresholdLabel', 'Threshold')}</Label>
                  <Input
                    type="number"
                    step="0.1"
                    value={signalForm.threshold}
                    onChange={e => setSignalForm(prev => ({ ...prev, threshold: parseFloat(e.target.value) || 0 }))}
                  />
                  <p className="text-xs text-muted-foreground mt-1">{t('signals.dialog.thresholdDesc', 'Value to compare against')}</p>
                </div>
              </div>
            )}
            <div>
              <Label>{t('signals.dialog.timeWindowLabel', 'Time Window')}</Label>
              <Select value={signalForm.time_window} onValueChange={v => setSignalForm(prev => ({ ...prev, time_window: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TIME_WINDOWS.map(tw => <SelectItem key={tw.value} value={tw.value}>{tw.label}</SelectItem>)}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground mt-1">
                {TIME_WINDOWS.find(tw => tw.value === signalForm.time_window)?.desc}
              </p>
            </div>

            <SignalMetricAnalysisPanel
              t={t}
              signalForm={signalForm}
              setSignalForm={setSignalForm}
              metricAnalysis={metricAnalysis}
              analysisLoading={analysisLoading}
              analysisSymbol={analysisSymbol}
              setAnalysisSymbol={setAnalysisSymbol}
              watchlistSymbols={watchlistSymbols}
            />

            <div className="flex items-center gap-2">
              <Switch checked={signalForm.enabled} onCheckedChange={v => setSignalForm(prev => ({ ...prev, enabled: v }))} />
              <Label>{t('signals.dialog.enabledLabel', 'Enabled')}</Label>
            </div>
          </div>

          {isFactorMode && (
            <div className="space-y-3 border-l pl-5">
              <div className="flex items-center gap-2">
                <FlaskConical className="w-4 h-4 text-[#B8860B]" />
                <span className="text-sm font-medium text-[#B8860B]">{t('signals.dialog.factorBrowser', 'Factor Browser')}</span>
              </div>
              <Input
                placeholder={t('signals.dialog.searchFactors', 'Search factors...')}
                value={factorSearch}
                onChange={e => setFactorSearch(e.target.value)}
                className="h-8 text-xs"
              />
              <div className="flex flex-wrap gap-1">
                {['all', ...Object.keys(FACTOR_CATEGORY_LABELS)].filter(c =>
                  c === 'all' || factorLibrary.some(f => f.category === c)
                ).map(c => (
                  <button key={c} type="button"
                    className={`text-[10px] px-1.5 py-0.5 rounded border ${factorCategory === c ? 'bg-[#B8860B]/20 text-[#B8860B] border-[#B8860B]/40' : 'text-muted-foreground border-transparent hover:bg-accent'}`}
                    onClick={() => setFactorCategory(c)}
                  >{c === 'all' ? 'All' : FACTOR_CATEGORY_LABELS[c] || c}</button>
                ))}
              </div>
              <ScrollArea className="h-[280px]">
                <div className="space-y-1 pr-2">
                  {factorLibrary
                    .filter(f => (factorCategory === 'all' || f.category === factorCategory) &&
                      (!factorSearch || f.name.toLowerCase().includes(factorSearch.toLowerCase()) || f.description.toLowerCase().includes(factorSearch.toLowerCase())))
                    .map(f => {
                      const isSelected = signalForm.metric === `factor:${f.name}`
                      return (
                        <button key={f.name} type="button"
                          className={`w-full text-left p-2 rounded text-xs transition-colors ${isSelected ? 'bg-[#B8860B]/15 border border-[#B8860B]/40' : 'hover:bg-accent border border-transparent'}`}
                          onClick={() => setSignalForm(prev => ({ ...prev, metric: `factor:${f.name}` }))}
                        >
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] px-1 rounded ${isSelected ? 'bg-[#B8860B]/30 text-[#D4A832]' : 'bg-muted text-muted-foreground'}`}>
                              {FACTOR_CATEGORY_LABELS[f.category] || f.category}
                            </span>
                            <span className={`font-mono font-medium ${isSelected ? 'text-[#D4A832]' : ''}`}>{f.name}</span>
                          </div>
                          <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">{f.description}</p>
                        </button>
                      )
                    })}
                </div>
              </ScrollArea>
              {signalForm.metric.startsWith('factor:') && (() => {
                const factor = factorLibrary.find(f => f.name === signalForm.metric.split(':')[1])
                if (!factor) return null
                return (
                  <div className="space-y-2 pt-2 border-t">
                    <div className="p-2 bg-[#B8860B]/10 rounded border border-[#B8860B]/30">
                      <code className="text-[11px] text-[#D4A832] break-all">{factor.expression}</code>
                    </div>
                    {analysisLoading ? (
                      <p className="text-[10px] text-muted-foreground">{t('signals.dialog.loadingAnalysis', 'Loading analysis...')}</p>
                    ) : (metricAnalysis as any)?.factor_percentiles ? (() => {
                      const pct = (metricAnalysis as any).factor_percentiles
                      const val = (metricAnalysis as any).factor_latest_value
                      const isZeroCentered = pct.min < 0 && pct.max > 0
                      return (
                        <div className="space-y-2">
                          {val != null && (
                            <p className="text-[10px]">
                              {t('signals.dialog.currentValue', 'Current value')}: <span className="font-mono font-bold">{Number(val).toFixed(6)}</span>
                              <span className="text-muted-foreground ml-1">(P{pct.current_pct?.toFixed(0)})</span>
                            </p>
                          )}
                          <div className="grid grid-cols-5 gap-1">
                            {['p5', 'p25', 'p50', 'p75', 'p95'].map(k => (
                              <button key={k} type="button"
                                className="p-1 bg-background rounded border text-center hover:bg-accent transition-colors"
                                onClick={() => setSignalForm(prev => ({ ...prev, threshold: pct[k] }))}
                                title={t('signals.dialog.clickToSetThreshold', 'Click to set as threshold')}
                              >
                                <div className="text-[9px] text-muted-foreground uppercase">{k}</div>
                                <div className="text-[10px] font-mono font-bold">{pct[k]?.toFixed(4)}</div>
                              </button>
                            ))}
                          </div>
                          <p className="text-[9px] text-muted-foreground">
                            {isZeroCentered
                              ? t('signals.dialog.zeroCenteredHint', 'Zero-centered factor: |x| > is useful for bidirectional deviation.')
                              : t('signals.dialog.factorThresholdHint', 'Set threshold based on the current value above. Factor triggers at K-line close.')}
                          </p>
                        </div>
                      )
                    })() : null}
                  </div>
                )
              })()}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={savingSignal}>{t('signals.dialog.cancel', 'Cancel')}</Button>
          <Button onClick={onSave} disabled={savingSignal || signalForm.metric === '_pick_factor'}>
            {savingSignal ? t('signals.dialog.saving', 'Saving...') : t('signals.dialog.save', 'Save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
