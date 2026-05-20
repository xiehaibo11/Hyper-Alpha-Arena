import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { apiRequest, getHyperliquidWatchlist, getBinanceWatchlist } from '@/lib/api'
import { RefreshCw, Info, CheckCircle2, FlaskConical, Plus } from 'lucide-react'
import FactorAnalysisDialog from './FactorAnalysisDialog'
import FactorLabDialog from './FactorLabDialog'
import FactorTable from './FactorTable'
import ExchangeIcon from '@/components/exchange/ExchangeIcon'
import PacmanLoader from '@/components/ui/pacman-loader'
import type { ExchangeId } from '@/lib/types/exchange'

const EXCHANGES: ExchangeId[] = ['hyperliquid', 'binance']
const FORWARD_PERIODS = ['1h', '4h', '12h', '24h']
const AUTO_COMPUTE_INTERVAL_SECONDS = 15 * 60
const PAGE_REFRESH_SECONDS = 60

interface FactorDef {
  name: string; category: string; display_name: string; display_name_zh?: string
  description: string; description_zh?: string; value_range?: string; unit?: string
}

export default function FactorLibrary() {
  const { t, i18n } = useTranslation()
  const isZh = i18n.language?.startsWith('zh')

  const [exchange, setExchange] = useState<ExchangeId>('hyperliquid')
  const [symbol, setSymbol] = useState('')
  const [symbols, setSymbols] = useState<string[]>([])
  const [period] = useState('1h')
  const [forwardPeriod, setForwardPeriod] = useState('4h')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [library, setLibrary] = useState<{ factors: FactorDef[]; categories: string[]; category_labels: any }>()
  const [values, setValues] = useState<any[]>([])
  const [effectiveness, setEffectiveness] = useState<any[]>([])
  const [lastComputeTime, setLastComputeTime] = useState<number | null>(null)
  const [computing, setComputing] = useState(false)
  const [computeDialogOpen, setComputeDialogOpen] = useState(false)
  const [computeResult, setComputeResult] = useState<any>(null)
  const [computeEstimate, setComputeEstimate] = useState<any>(null)
  const [computeProgress, setComputeProgress] = useState<any>(null)
  const [dialogStep, setDialogStep] = useState<'confirm' | 'progress' | 'done'>('confirm')
  const [countdown, setCountdown] = useState('')
  const [loading, setLoading] = useState(true)
  const [sortCol, setSortCol] = useState<string>('icir')
  const [sortDesc, setSortDesc] = useState(true)

  // Custom Factor Lab state
  const [labDialogOpen, setLabDialogOpen] = useState(false)
  const [editingFactorId, setEditingFactorId] = useState<number | null>(null)
  const [customFactors, setCustomFactors] = useState<any[]>([])

  // Factor Analysis Dialog state
  const [analysisOpen, setAnalysisOpen] = useState(false)
  const [analysisFactor, setAnalysisFactor] = useState<{ name: string; displayName: string }>({ name: '', displayName: '' })

  useEffect(() => {
    apiRequest('/factors/library').then(r => r.json()).then(setLibrary).catch(() => {})
  }, [])

  useEffect(() => {
    const load = async () => {
      try {
        const data = exchange === 'binance'
          ? await getBinanceWatchlist()
          : await getHyperliquidWatchlist()
        const syms = data.symbols || []
        setSymbols(syms)
        if (syms.length > 0 && !syms.includes(symbol)) setSymbol(syms[0])
      } catch { setSymbols([]) }
    }
    load()
  }, [exchange])

  const loadData = useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    try {
      const [valRes, effRes, statusRes] = await Promise.all([
        apiRequest(`/factors/values?symbol=${symbol}&period=${period}&exchange=${exchange}`).then(r => r.json()).catch(() => ({ values: [] })),
        apiRequest(`/factors/effectiveness?symbol=${symbol}&period=${period}&forward_period=${forwardPeriod}&exchange=${exchange}`).then(r => r.json()).catch(() => ({ items: [] })),
        apiRequest('/factors/status').then(r => r.json()).catch(() => null),
      ])
      setValues(valRes.values || [])
      setEffectiveness(effRes.items || [])
      if (statusRes?.last_compute_time) {
        setLastComputeTime(statusRes.last_compute_time[exchange] || null)
      }
    } finally { setLoading(false) }
  }, [symbol, period, exchange, forwardPeriod])

  useEffect(() => { loadData() }, [loadData])
  useEffect(() => {
    if (!symbol) return
    const interval = window.setInterval(() => { loadData() }, PAGE_REFRESH_SECONDS * 1000)
    return () => window.clearInterval(interval)
  }, [symbol, loadData])

  const loadCustomFactors = useCallback(async () => {
    try {
      const res = await apiRequest('/factors/custom').then(r => r.json())
      setCustomFactors(res.items || [])
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadCustomFactors() }, [loadCustomFactors])

  // Custom Factor Lab handlers
  const openLabDialog = (factorId?: number) => {
    setEditingFactorId(factorId || null)
    setLabDialogOpen(true)
  }

  const handleDeleteCustom = async (id: number) => {
    if (!confirm(t('factors.deleteConfirm'))) return
    try {
      await apiRequest(`/factors/custom/${id}`, { method: 'DELETE' })
      await loadCustomFactors()
    } catch { /* ignore */ }
  }

  // Compute handlers (unchanged)
  useEffect(() => {
    if (!lastComputeTime) { setCountdown(''); return }
    const update = () => {
      const nextTs = lastComputeTime + AUTO_COMPUTE_INTERVAL_SECONDS
      const remaining = nextTs - Date.now() / 1000
      if (remaining <= 0) { setCountdown(''); return }
      const m = Math.floor(remaining / 60)
      const s = Math.floor(remaining % 60)
      setCountdown(`${m}:${s.toString().padStart(2, '0')}`)
    }
    update()
    const interval = setInterval(update, 1000)
    return () => clearInterval(interval)
  }, [lastComputeTime])

  const handleComputeClick = async () => {
    setComputeDialogOpen(true)
    setDialogStep('confirm')
    setComputeResult(null)
    setComputeProgress(null)
    setComputeEstimate(null)
    try {
      const est = await apiRequest(`/factors/compute/estimate?exchange=${exchange}`).then(r => r.json())
      setComputeEstimate(est)
    } catch { /* ignore */ }
  }

  const handleComputeConfirm = async () => {
    setDialogStep('progress')
    setComputing(true)
    setComputeProgress(null)
    try {
      const startRes = await apiRequest('/factors/compute', {
        method: 'POST', body: JSON.stringify({ exchange, period }),
      }).then(r => r.json())
      if (startRes.status === 'already_running') {
        setComputeResult({ error: t('factors.alreadyRunning') })
        setDialogStep('done'); setComputing(false); return
      }
      const poll = setInterval(async () => {
        try {
          const prog = await apiRequest('/factors/compute/progress').then(r => r.json())
          setComputeProgress(prog)
          if (prog.status === 'done' || prog.status === 'error' || prog.status === 'idle') {
            clearInterval(poll); setComputeResult(prog)
            setDialogStep('done'); setComputing(false); await loadData()
          }
        } catch { /* ignore */ }
      }, 1500)
    } catch (e: any) {
      setComputeResult({ error: e.message || 'Unknown error' })
      setDialogStep('done'); setComputing(false)
    }
  }

  const toggleSort = (col: string) => {
    if (sortCol === col) setSortDesc(!sortDesc)
    else { setSortCol(col); setSortDesc(true) }
  }

  // Merge library (builtin + custom) with values and effectiveness data
  const mergedRows = useMemo(() => {
    if (!library) return []
    const valMap = new Map(values.map(v => [v.factor_name, v]))
    const effMap = new Map(effectiveness.map(e => [e.factor_name, e]))

    const rows = library.factors
      .filter((f: any) => categoryFilter === 'all' || f.category === categoryFilter)
      .map((f: any) => {
        const v = valMap.get(f.name)
        const e = effMap.get(f.name)
        const isCustom = f.source !== 'builtin' && f.source !== 'builtin_expression'
        return {
          ...f, value: v?.value ?? null, timestamp: v?.timestamp, ...e,
          _isCustom: isCustom, _customId: f.custom_id ?? null, _expression: f.expression ?? null,
        }
      })

    if (['ic_mean', 'icir', 'win_rate'].includes(sortCol)) {
      rows.sort((a: any, b: any) => {
        const av = Math.abs(a[sortCol] ?? 0)
        const bv = Math.abs(b[sortCol] ?? 0)
        return sortDesc ? bv - av : av - bv
      })
    }
    return rows
  }, [library, values, effectiveness, categoryFilter, sortCol, sortDesc])

  const categories = library?.categories || []
  const catLabels = library?.category_labels || {}
  const getCatLabel = (cat: string) => {
    if (cat === 'custom') return t('factors.customTag')
    const l = catLabels[cat]
    return l ? (isZh ? l.zh : l.en) : cat
  }
  const getFactorDesc = (f: any) => isZh ? (f.description_zh || f.description) : f.description
  const formatLastUpdate = () => {
    if (!lastComputeTime) return '--'
    return new Date(lastComputeTime * 1000).toLocaleString()
  }

  if (loading && !library) {
    return <div className="flex items-center justify-center h-40 text-muted-foreground">{t('factors.loading')}</div>
  }

  return (
    <TooltipProvider>
      <div className="flex flex-col flex-1 min-h-0 space-y-3">
        {/* Controls row */}
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">{t('factors.exchange')}</label>
            <Select value={exchange} onValueChange={(v) => setExchange(v as ExchangeId)}>
              <SelectTrigger className="w-36">
                <div className="flex items-center gap-2">
                  <ExchangeIcon exchangeId={exchange} size={16} />
                  <span className="capitalize">{exchange}</span>
                </div>
              </SelectTrigger>
              <SelectContent>
                {EXCHANGES.map(e => (
                  <SelectItem key={e} value={e}>
                    <div className="flex items-center gap-2">
                      <ExchangeIcon exchangeId={e} size={16} />
                      <span className="capitalize">{e}</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {symbols.length > 0 ? (
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Symbol</label>
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {symbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <span className="text-sm text-muted-foreground pb-1">{t('factors.noSymbols')}</span>
          )}

          <div className="flex flex-col gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <label className="text-xs text-muted-foreground flex items-center gap-1 cursor-help">
                  {t('factors.forwardPeriodLabel')}
                  <Info className="h-3 w-3" />
                </label>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs max-w-[200px]">{t('factors.forwardPeriodHint')}</p></TooltipContent>
            </Tooltip>
            <Select value={forwardPeriod} onValueChange={setForwardPeriod}>
              <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
              <SelectContent>
                {FORWARD_PERIODS.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <Button variant="outline" size="sm" className="self-end" disabled={computing || !symbol}
            onClick={handleComputeClick}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1 ${computing ? 'animate-spin' : ''}`} />
            {computing ? t('factors.computing') : t('factors.manualCompute')}
          </Button>

          <Button size="sm" className="self-end gap-1" onClick={() => openLabDialog()}>
            <Plus className="h-3.5 w-3.5" />
            <FlaskConical className="h-3.5 w-3.5" />
            {t('factors.customLab')}
          </Button>

          <span className="text-xs text-muted-foreground ml-auto self-end pb-1">
            {t('factors.lastUpdate')}: {formatLastUpdate()}
            {countdown && ` | ${t('factors.nextCompute')}: ${countdown}`}
          </span>
        </div>

        {/* Compute dialog */}
        <Dialog open={computeDialogOpen} onOpenChange={(open) => {
          if (!open && computing) return
          setComputeDialogOpen(open)
        }}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>{t('factors.computeConfirmTitle')}</DialogTitle>
              <DialogDescription>{exchange} / {period} K-line</DialogDescription>
            </DialogHeader>
            {dialogStep === 'confirm' && (
              <>
                <div className="py-4 space-y-3">
                  <p className="text-sm">{t('factors.confirmCompute')}</p>
                  {computeEstimate && (
                    <div className="rounded-md bg-muted p-3 space-y-2 text-xs">
                      <div>
                        <span className="text-muted-foreground">{t('factors.estimateSymbols')} ({computeEstimate.symbol_count}):</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {computeEstimate.symbols?.map((s: string) => (
                            <Badge key={s} variant="outline" className="text-xs">{s}</Badge>
                          ))}
                        </div>
                      </div>
                      <p>{t('factors.estimateFactors')}: <span className="font-medium">{computeEstimate.factor_count}</span></p>
                      <p>{t('factors.estimateWindows')}: <span className="font-medium">{computeEstimate.forward_periods?.join(', ')}</span></p>
                      <p>{t('factors.estimateTime')}: <span className="font-medium">~{Math.max(1, Math.ceil((computeEstimate.estimated_seconds || 0) / 60))} min</span></p>
                    </div>
                  )}
                </div>
                <DialogFooter className="gap-2 sm:gap-0">
                  <DialogClose asChild><Button variant="outline" size="sm">{t('common.cancel')}</Button></DialogClose>
                  <Button size="sm" onClick={handleComputeConfirm}
                    disabled={!computeEstimate || computeEstimate.symbol_count === 0}>
                    {t('factors.startCompute')}
                  </Button>
                </DialogFooter>
              </>
            )}
            {dialogStep === 'progress' && (
              <div className="py-6">
                <div className="flex flex-col items-center gap-3">
                  <PacmanLoader className="w-16 h-8 text-primary" />
                  <p className="text-sm font-medium">{t('factors.computing')}</p>
                  {computeProgress?.status === 'running' && (
                    <div className="w-full space-y-2">
                      <div className="flex justify-between text-xs text-muted-foreground">
                        <span>{computeProgress.phase === 'values' ? t('factors.phaseValues') : t('factors.phaseEffectiveness')}</span>
                        <span>{computeProgress.current_symbol} ({computeProgress.completed}/{computeProgress.total})</span>
                      </div>
                      <div className="w-full bg-muted rounded-full h-2">
                        <div className="bg-primary h-2 rounded-full transition-all duration-500"
                          style={{ width: `${computeProgress.total > 0 ? (computeProgress.completed / computeProgress.total) * 100 : 0}%` }} />
                      </div>
                      {computeProgress.phase === 'effectiveness' && computeProgress.current_factor && (
                        <div className="space-y-1">
                          <div className="flex justify-between text-xs text-muted-foreground">
                            <span className="font-mono">{computeProgress.current_factor}</span>
                            <span>{computeProgress.factor_completed}/{computeProgress.factor_total}</span>
                          </div>
                          <div className="w-full bg-muted rounded-full h-1.5">
                            <div className="bg-primary/60 h-1.5 rounded-full transition-all duration-300"
                              style={{ width: `${computeProgress.factor_total > 0 ? (computeProgress.factor_completed / computeProgress.factor_total) * 100 : 0}%` }} />
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
            {dialogStep === 'done' && (
              <>
                <div className="py-4">
                  {computeResult?.error ? (
                    <div className="text-center text-red-500 text-sm">{computeResult.error}</div>
                  ) : (
                    <div className="flex flex-col items-center gap-3">
                      <CheckCircle2 className="h-8 w-8 text-green-500" />
                      <p className="text-sm font-medium">{t('factors.computeSuccess')}</p>
                      <div className="text-xs text-muted-foreground space-y-1">
                        <p>{t('factors.resultSymbols')}: {computeResult?.values_computed ?? 0}</p>
                        <p>{t('factors.resultEffectiveness')}: {computeResult?.effectiveness_computed ?? 0}</p>
                      </div>
                    </div>
                  )}
                </div>
                <DialogFooter>
                  <DialogClose asChild><Button variant="outline" size="sm">{t('common.close')}</Button></DialogClose>
                </DialogFooter>
              </>
            )}
          </DialogContent>
        </Dialog>

        <FactorLabDialog
          open={labDialogOpen}
          onOpenChange={setLabDialogOpen}
          editingFactor={editingFactorId ? customFactors.find(f => f.id === editingFactorId) || null : null}
          exchange={exchange}
          symbol={symbol}
          symbols={symbols}
          isZh={isZh}
          t={t}
          onExchangeChange={setExchange}
          onSymbolChange={setSymbol}
          onSaved={loadCustomFactors}
        />

        {/* Category filter - includes Custom */}
        <div className="flex gap-1.5 flex-wrap">
          <Badge variant={categoryFilter === 'all' ? 'default' : 'outline'} className="cursor-pointer text-xs"
            onClick={() => setCategoryFilter('all')}>All</Badge>
          {categories.map(c => (
            <Badge key={c} variant={categoryFilter === c ? 'default' : 'outline'}
              className="cursor-pointer text-xs" onClick={() => setCategoryFilter(c)}>
              {getCatLabel(c)}
            </Badge>
          ))}
          {customFactors.length > 0 && (
            <Badge
              variant={categoryFilter === 'custom' ? 'default' : 'outline'}
              className={`cursor-pointer text-xs ${categoryFilter !== 'custom' ? 'bg-purple-500/10 text-purple-400 border-purple-500/30 hover:bg-purple-500/20' : 'bg-purple-600'}`}
              onClick={() => setCategoryFilter('custom')}>
              {t('factors.customTag')} ({customFactors.length})
            </Badge>
          )}
        </div>

        <FactorTable
          rows={mergedRows}
          t={t}
          isZh={isZh}
          sortCol={sortCol}
          getCatLabel={getCatLabel}
          getFactorDesc={getFactorDesc}
          toggleSort={toggleSort}
          onAnalyze={(factor) => { setAnalysisFactor(factor); setAnalysisOpen(true) }}
          onEditCustom={openLabDialog}
          onDeleteCustom={handleDeleteCustom}
        />
      </div>
      <FactorAnalysisDialog
        open={analysisOpen}
        onOpenChange={setAnalysisOpen}
        factorName={analysisFactor.name}
        displayName={analysisFactor.displayName}
        symbol={symbol}
        period={period}
        exchange={exchange}
        forwardPeriod={forwardPeriod}
      />
    </TooltipProvider>
  )
}
