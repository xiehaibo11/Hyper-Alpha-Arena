import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AnalysisReport, AnalysisTrap, getAnalysis } from '@/lib/eventContractApi'

interface Props { exchange: string; symbol: string; period?: string }

const BIAS = {
  long: { label: '做多 LONG', cls: 'bg-green-500/15 text-green-500 border-green-500/40' },
  short: { label: '做空 SHORT', cls: 'bg-red-500/15 text-red-500 border-red-500/40' },
  neutral: { label: '观望 WAIT', cls: 'bg-muted text-muted-foreground border-border' },
}
const SEV = {
  high: 'border-red-500/50 bg-red-500/10 text-red-500',
  medium: 'border-amber-500/50 bg-amber-500/10 text-amber-500',
  low: 'border-muted bg-muted/40 text-muted-foreground',
}

function TrapItem({ t }: { t: AnalysisTrap }) {
  return (
    <div className={`text-xs rounded border px-2 py-1.5 ${SEV[t.severity]}`}>
      <div className="font-semibold">⚠ {t.title}</div>
      <div className="opacity-80 mt-0.5 leading-snug">{t.detail}</div>
    </div>
  )
}

// 左侧分析面板：当前 K 线高级解读 + 做多/做空理由 + 不能踩的坑（陷阱图）。
export default function AnalysisPanel({ exchange, symbol, period = '1m' }: Props) {
  const { t } = useTranslation()
  const [rep, setRep] = useState<AnalysisReport | null>(null)
  const [ok, setOk] = useState(true)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const r = await getAnalysis(symbol, exchange, period)
        if (!alive) return
        setOk(r.available)
        setRep(r.report)
      } catch { /* transient */ }
    }
    tick()
    const id = setInterval(tick, 15000)
    return () => { alive = false; clearInterval(id) }
  }, [exchange, symbol, period])

  const b = rep ? BIAS[rep.bias] : BIAS.neutral
  return (
    <div className="w-72 shrink-0 border rounded-lg p-4 bg-card space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">{t('eventContract.analysis', '高级分析')} · {symbol}</div>
        <span className="text-[10px] text-muted-foreground">{period}</span>
      </div>

      {!ok || !rep ? (
        <div className="text-xs text-muted-foreground py-6 text-center">
          {t('eventContract.analysisNoData', '暂无足够 K 线数据')}
        </div>
      ) : (
        <>
          <div className={`text-xl font-bold px-3 py-2 rounded-lg border text-center ${b.cls}`}>
            {b.label}
            <span className="block text-xs font-normal opacity-70 mt-0.5">
              {t('eventContract.confidence', '置信度')} {(rep.confidence * 100).toFixed(0)}%
            </span>
          </div>

          <div className="grid grid-cols-2 gap-1.5 text-xs">
            <div className="rounded border px-2 py-1">趋势 <b>{({ up: '↑上升', down: '↓下降', mixed: '↔震荡' } as any)[rep.trend.direction]}</b>{rep.trend.strong && <span className="text-amber-500"> 强</span>}</div>
            <div className="rounded border px-2 py-1">RSI <b>{rep.momentum.rsi?.toFixed(0) ?? '—'}</b></div>
            <div className="rounded border px-2 py-1">MACD <b>{rep.momentum.macd_cross === 'bull' ? '金叉' : '死叉'}</b></div>
            <div className="rounded border px-2 py-1">量价 <b>{rep.volume.price_vs_vwma === 'above' ? '价>均量' : rep.volume.price_vs_vwma === 'below' ? '价<均量' : '—'}</b></div>
          </div>

          {rep.long_reasons.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-green-500 mb-1">{t('eventContract.longReasons', '做多理由')}</div>
              <ul className="space-y-1">{rep.long_reasons.map((r, i) => <li key={i} className="text-xs text-muted-foreground leading-snug">• {r}</li>)}</ul>
            </div>
          )}
          {rep.short_reasons.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-red-500 mb-1">{t('eventContract.shortReasons', '做空理由')}</div>
              <ul className="space-y-1">{rep.short_reasons.map((r, i) => <li key={i} className="text-xs text-muted-foreground leading-snug">• {r}</li>)}</ul>
            </div>
          )}

          <div>
            <div className="text-xs font-semibold mb-1">{t('eventContract.traps', '不能踩的坑 / 陷阱')}</div>
            {rep.traps.length === 0
              ? <div className="text-xs text-muted-foreground">{t('eventContract.noTraps', '当前无明显陷阱')}</div>
              : <div className="space-y-1.5">{rep.traps.map((tp) => <TrapItem key={tp.id} t={tp} />)}</div>}
          </div>

          <div className="text-[11px] text-muted-foreground border-t pt-2 leading-snug">{rep.summary}</div>
        </>
      )}
    </div>
  )
}
