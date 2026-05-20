import type { TFunction } from 'i18next'
import { useEffect, useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import ExchangeIcon from '@/components/exchange/ExchangeIcon'
import PacmanLoader from '@/components/ui/pacman-loader'
import { apiRequest } from '@/lib/api'
import type { ExchangeId } from '@/lib/types/exchange'
import { IcBadge, translateFactorError, WinRateBadge } from './FactorDisplayHelpers'

const FUNC_CATEGORIES: { key: string; en: string; zh: string; fns: string[] }[] = [
  { key: 'ma', en: 'Moving Avg', zh: '均线', fns: ['SMA', 'EMA', 'WMA'] },
  { key: 'mom', en: 'Momentum', zh: '动量', fns: ['RSI', 'ROC', 'MOM', 'MACD', 'MACD_SIGNAL', 'MACD_HIST', 'STOCH_K', 'STOCH_D', 'CCI', 'WILLR'] },
  { key: 'vol', en: 'Volatility', zh: '波动率', fns: ['ATR', 'STDDEV', 'BBANDS_UPPER', 'BBANDS_MID', 'BBANDS_LOWER'] },
  { key: 'volume', en: 'Volume', zh: '成交量', fns: ['OBV', 'VWAP'] },
  { key: 'ts', en: 'Time Series', zh: '时间序列', fns: ['DELAY', 'DELTA', 'TS_MAX', 'TS_MIN', 'TS_RANK'] },
  { key: 'math', en: 'Math', zh: '数学', fns: ['ABS', 'LOG', 'SIGN', 'MAX', 'MIN', 'RANK', 'ZSCORE'] },
]

const FUNC_TEMPLATES: Record<string, string> = {
  SMA: 'SMA(close, 20)', EMA: 'EMA(close, 20)', WMA: 'WMA(close, 20)',
  RSI: 'RSI(close, 14)', ROC: 'ROC(close, 10)', MOM: 'MOM(close, 10)',
  MACD: 'MACD(close, 12, 26, 9)', MACD_SIGNAL: 'MACD_SIGNAL(close, 12, 26, 9)',
  MACD_HIST: 'MACD_HIST(close, 12, 26, 9)',
  STOCH_K: 'STOCH_K(high, low, close, 14)', STOCH_D: 'STOCH_D(high, low, close, 14)',
  CCI: 'CCI(high, low, close, 20)', WILLR: 'WILLR(high, low, close, 14)',
  ATR: 'ATR(high, low, close, 14)', STDDEV: 'STDDEV(close, 20)',
  BBANDS_UPPER: 'BBANDS_UPPER(close, 20)', BBANDS_MID: 'BBANDS_MID(close, 20)',
  BBANDS_LOWER: 'BBANDS_LOWER(close, 20)',
  OBV: 'OBV(close, volume)', VWAP: 'VWAP(high, low, close, volume)',
  DELAY: 'DELAY(close, 1)', DELTA: 'DELTA(close, 1)',
  TS_MAX: 'TS_MAX(close, 20)', TS_MIN: 'TS_MIN(close, 20)', TS_RANK: 'TS_RANK(close, 20)',
  ABS: 'ABS()', LOG: 'LOG()', SIGN: 'SIGN()',
  MAX: 'MAX(, )', MIN: 'MIN(, )', RANK: 'RANK(close)', ZSCORE: 'ZSCORE(close)',
}

interface FactorLabDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  editingFactor: any | null
  exchange: ExchangeId
  symbol: string
  symbols: string[]
  isZh: boolean
  t: TFunction
  onExchangeChange: (exchange: ExchangeId) => void
  onSymbolChange: (symbol: string) => void
  onSaved: () => Promise<void>
}

export default function FactorLabDialog({
  open,
  onOpenChange,
  editingFactor,
  exchange,
  symbol,
  symbols,
  isZh,
  t,
  onExchangeChange,
  onSymbolChange,
  onSaved,
}: FactorLabDialogProps) {
  const [expression, setExpression] = useState('')
  const [evalResult, setEvalResult] = useState<any>(null)
  const [evalError, setEvalError] = useState('')
  const [evaluating, setEvaluating] = useState(false)
  const [funcCatTab, setFuncCatTab] = useState(FUNC_CATEGORIES[0].key)
  const [saveName, setSaveName] = useState('')
  const [saveDesc, setSaveDesc] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setExpression(editingFactor?.expression || '')
    setSaveName(editingFactor?.name || '')
    setSaveDesc(editingFactor?.description || '')
    setEvalResult(null)
    setEvalError('')
  }, [open, editingFactor])

  const handleEvaluate = async () => {
    if (!expression.trim() || !symbol) return
    setEvaluating(true)
    setEvalResult(null)
    setEvalError('')
    try {
      const res = await apiRequest('/factors/evaluate', {
        method: 'POST',
        body: JSON.stringify({ expression: expression.trim(), symbol, exchange, period: '1h' }),
      }).then(r => r.json())
      if (res.status === 'error') setEvalError(translateFactorError(res.error, isZh ? 'zh' : 'en'))
      else setEvalResult(res)
    } catch (e: any) {
      setEvalError(e.message || 'Unknown error')
    } finally {
      setEvaluating(false)
    }
  }

  const handleSave = async () => {
    if (!saveName.trim() || !expression.trim()) return
    setSaving(true)
    setEvalError('')
    try {
      if (editingFactor?.id) {
        await apiRequest(`/factors/custom/${editingFactor.id}`, { method: 'DELETE' })
      }
      const res = await apiRequest('/factors/custom', {
        method: 'POST',
        body: JSON.stringify({
          name: saveName.trim(), expression: expression.trim(),
          description: saveDesc.trim(), category: 'custom', source: 'manual',
        }),
      }).then(r => r.json())
      if (res.status === 'ok') {
        onOpenChange(false)
        await onSaved()
      } else {
        setEvalError(translateFactorError(res.error || 'Save failed', isZh ? 'zh' : 'en'))
      }
    } catch (e: any) {
      setEvalError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const insertFunction = (funcName: string) => {
    const template = FUNC_TEMPLATES[funcName] || funcName + '('
    setExpression(prev => prev.trim() ? `${prev} ${template}` : template)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogDescription>{t('factors.customLabDesc')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex gap-3 items-end">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">{t('factors.exchange')}</label>
              <Select value={exchange} onValueChange={(v) => onExchangeChange(v as ExchangeId)}>
                <SelectTrigger className="w-36">
                  <div className="flex items-center gap-2">
                    <ExchangeIcon exchangeId={exchange} size={16} />
                    <span className="capitalize">{exchange}</span>
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {(['hyperliquid', 'binance'] as ExchangeId[]).map(e => (
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
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Symbol</label>
              <Select value={symbol} onValueChange={onSymbolChange}>
                <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {symbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">{t('factors.expression')}</label>
            <div className="flex gap-2">
              <Input
                className="font-mono text-sm flex-1"
                placeholder={t('factors.expressionPlaceholder')}
                value={expression}
                onChange={(e) => setExpression(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleEvaluate()}
              />
              <Button disabled={evaluating || !expression.trim() || !symbol} onClick={handleEvaluate}>
                {evaluating ? <><PacmanLoader className="w-5 h-4 mr-1.5" />{t('factors.evaluating')}</> : t('factors.evaluate')}
              </Button>
            </div>
            {evalError && (
              <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-md px-3 py-2">
                {evalError}
              </div>
            )}
          </div>

          <div className="rounded-md border overflow-hidden">
            <div className="flex border-b bg-muted/30">
              {FUNC_CATEGORIES.map(cat => (
                <button key={cat.key}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors border-b-2 -mb-px ${
                    funcCatTab === cat.key ? 'border-primary text-foreground bg-background' : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                  onClick={() => setFuncCatTab(cat.key)}>
                  {isZh ? cat.zh : cat.en}
                </button>
              ))}
            </div>
            <div className="p-2 flex gap-1.5 flex-wrap">
              {(FUNC_CATEGORIES.find(c => c.key === funcCatTab)?.fns || []).map(fn => (
                <Tooltip key={fn}>
                  <TooltipTrigger asChild>
                    <button className="px-2.5 py-1 rounded bg-muted hover:bg-primary/10 text-xs font-mono border border-transparent hover:border-primary/30 transition-colors"
                      onClick={() => insertFunction(fn)}>{fn}</button>
                  </TooltipTrigger>
                  <TooltipContent side="top"><p className="text-xs font-mono">{FUNC_TEMPLATES[fn]}</p></TooltipContent>
                </Tooltip>
              ))}
            </div>
          </div>

          {evalResult && (
            <div className="space-y-3 border-t pt-3">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                <span className="text-sm font-medium">{evalResult.symbol}</span>
                <span className="text-xs text-muted-foreground">
                  {t('factors.latestValue')}: <span className="font-mono text-foreground">{evalResult.latest_value?.toFixed(6) ?? '—'}</span>
                </span>
              </div>
              <div className="grid grid-cols-4 gap-3">
                {Object.entries(evalResult.effectiveness as Record<string, any>).map(([fp, m]: [string, any]) => (
                  <div key={fp} className="rounded-lg border p-3 space-y-1.5">
                    <div className="font-medium text-sm text-center">{fp}</div>
                    <div className="flex justify-between text-xs"><span className="text-muted-foreground">IC</span><IcBadge value={m.ic_mean} /></div>
                    <div className="flex justify-between text-xs"><span className="text-muted-foreground">ICIR</span><span className="font-mono">{m.icir?.toFixed(2)}</span></div>
                    <div className="flex justify-between text-xs"><span className="text-muted-foreground">{t('factors.winRate')}</span><WinRateBadge value={m.win_rate} /></div>
                    <div className="flex justify-between text-xs"><span className="text-muted-foreground">N</span><span>{m.sample_count}</span></div>
                  </div>
                ))}
              </div>
              <div className="border-t pt-3 space-y-3">
                <label className="text-sm font-medium">{t('factors.saveToLibrary')}</label>
                <div className="grid grid-cols-2 gap-3">
                  <Input className="text-sm" placeholder={t('factors.factorNamePlaceholder')} value={saveName} onChange={e => setSaveName(e.target.value)} />
                  <Input className="text-sm" placeholder={t('factors.descriptionPlaceholder')} value={saveDesc} onChange={e => setSaveDesc(e.target.value)} />
                </div>
                <Button disabled={saving || !saveName.trim()} onClick={handleSave} className="gap-1.5">
                  {saving ? t('factors.saving') : <><CheckCircle2 className="h-4 w-4" />{t('factors.saveToLibrary')}</>}
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
