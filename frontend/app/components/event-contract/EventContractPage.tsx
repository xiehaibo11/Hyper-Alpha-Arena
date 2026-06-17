import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BacktestResult, DailyStats, LiveSignal,
  compareBacktest, getDailyStats, getLiveSignals,
} from '@/lib/eventContractApi'
import EventContractConfigPanel from './EventContractConfigPanel'
import EventContractChart from './EventContractChart'
import AnalysisPanel from './AnalysisPanel'
import HistoryChart from './HistoryChart'

const EXCHANGES = ['hyperliquid', 'binance', 'okx'] as const

function DirectionBadge({ d }: { d: LiveSignal['direction'] }) {
  const map = {
    long: { label: '多 LONG', cls: 'bg-green-500/15 text-green-500 border-green-500/40' },
    short: { label: '空 SHORT', cls: 'bg-red-500/15 text-red-500 border-red-500/40' },
    none: { label: '无 NONE', cls: 'bg-muted text-muted-foreground border-border' },
  }[d]
  return (
    <div className={`text-2xl font-bold px-4 py-3 rounded-lg border text-center ${map.cls}`}>
      {map.label}
    </div>
  )
}

function DailyPanel({ s }: { s: DailyStats | null }) {
  const { t } = useTranslation()
  const wr = s ? (s.win_rate * 100).toFixed(1) : '0.0'
  const lr = s ? (s.loss_rate * 100).toFixed(1) : '0.0'
  const good = s && s.win_rate >= 0.66
  return (
    <div className="w-56 shrink-0 border rounded-lg p-4 bg-card">
      <div className="text-sm font-semibold mb-3">{t('eventContract.todayStats', '今日统计 (00:00 起)')}</div>
      <table className="w-full text-sm">
        <tbody>
          <tr><td className="text-muted-foreground py-1">{t('eventContract.totalOrders', '开单总数')}</td><td className="text-right font-medium">{s?.total ?? 0}</td></tr>
          <tr><td className="text-muted-foreground py-1">{t('eventContract.wins', '赢')}</td><td className="text-right font-medium text-green-500">{s?.wins ?? 0}</td></tr>
          <tr><td className="text-muted-foreground py-1">{t('eventContract.losses', '输')}</td><td className="text-right font-medium text-red-500">{s?.losses ?? 0}</td></tr>
          <tr><td className="text-muted-foreground py-1">{t('eventContract.pending', '未结算')}</td><td className="text-right font-medium">{s?.pending ?? 0}</td></tr>
          <tr className="border-t"><td className="py-1 font-semibold">{t('eventContract.winRate', '胜率')}</td><td className={`text-right font-bold ${good ? 'text-green-500' : ''}`}>{wr}%</td></tr>
          <tr><td className="py-1 font-semibold">{t('eventContract.lossRate', '输率')}</td><td className="text-right font-bold text-red-500">{lr}%</td></tr>
        </tbody>
      </table>
      <div className="text-[10px] text-muted-foreground mt-2">{t('eventContract.tzNote', '每日 00:00 重置')} · {s?.tz || ''}</div>
    </div>
  )
}

export default function EventContractPage() {
  const { t } = useTranslation()
  const [signals, setSignals] = useState<LiveSignal[]>([])
  const [stats, setStats] = useState<DailyStats | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string>('')
  const [btSymbol, setBtSymbol] = useState('BTC')
  const [btExpiry, setBtExpiry] = useState(5)
  const [bt, setBt] = useState<{ order_flow: BacktestResult[]; ta: BacktestResult[] } | null>(null)
  const [btLoading, setBtLoading] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [exchange, setExchange] = useState('hyperliquid')
  const [chartSymbol, setChartSymbol] = useState('BTC')
  const [chartExpiry, setChartExpiry] = useState(5)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const [sig, st] = await Promise.all([getLiveSignals(exchange), getDailyStats()])
        if (!alive) return
        setSignals(sig.signals)
        setStats(st)
        setUpdatedAt(new Date().toLocaleTimeString())
      } catch { /* ignore transient */ }
    }
    tick()
    const id = setInterval(tick, 15000)
    return () => { alive = false; clearInterval(id) }
  }, [exchange])

  const runBacktest = async () => {
    setBtLoading(true)
    try {
      setBt(await compareBacktest(exchange, btSymbol, btExpiry))
    } catch { setBt(null) } finally { setBtLoading(false) }
  }

  const cards = signals
  return (
    <div className="h-full overflow-auto">
      <div className="flex gap-4 items-start">
        <AnalysisPanel exchange={exchange} symbol={chartSymbol} period="1m" />
        <div className="flex-1">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h2 className="text-lg font-semibold">{t('eventContract.signalBoard', '事件合约信号 (多/空/无)')}</h2>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">{t('eventContract.platform', '平台')}:</span>
              <select className="border rounded px-2 py-1 text-sm bg-background"
                value={exchange} onChange={(e) => setExchange(e.target.value)}>
                {EXCHANGES.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
              <span className="text-xs text-muted-foreground">{t('eventContract.updated', '更新')}: {updatedAt}</span>
              <button onClick={() => setShowConfig((v) => !v)}
                className="text-xs px-2 py-1 rounded border hover:bg-muted">
                ⚙ {t('eventContract.config', '配置')}
              </button>
            </div>
          </div>
          {showConfig && <div className="mb-3"><EventContractConfigPanel onClose={() => setShowConfig(false)} /></div>}
          <div className="grid grid-cols-2 gap-3">
            {cards.map((c) => (
              <div key={`${c.symbol}-${c.expiry_minutes}`} className="border rounded-lg p-4 bg-card">
                <div className="flex items-center justify-between mb-3">
                  <span className="font-semibold">{c.symbol}</span>
                  <span className="text-sm text-muted-foreground">{c.expiry_minutes} {t('eventContract.min', '分钟')}</span>
                </div>
                <DirectionBadge d={c.direction} />
                <div className="text-xs text-muted-foreground mt-2">
                  {t('eventContract.price', '现价')}: {c.price != null ? c.price : '—'}
                </div>
              </div>
            ))}
            {cards.length === 0 && (
              <div className="col-span-2 text-sm text-muted-foreground p-8 text-center">
                {t('eventContract.loading', '加载中…')}
              </div>
            )}
          </div>
        </div>
        <DailyPanel s={stats} />
      </div>

      <div className="mt-6 border rounded-lg p-4 bg-card">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <h3 className="font-semibold">{t('eventContract.chart', '信号箭头图')}</h3>
          <select className="border rounded px-2 py-1 text-sm bg-background" value={chartSymbol} onChange={(e) => setChartSymbol(e.target.value)}>
            <option value="BTC">BTC</option><option value="ETH">ETH</option>
          </select>
          <select className="border rounded px-2 py-1 text-sm bg-background" value={chartExpiry} onChange={(e) => setChartExpiry(Number(e.target.value))}>
            <option value={5}>5min</option><option value={10}>10min</option>
          </select>
          <span className="text-xs text-muted-foreground">
            ↑ {t('eventContract.arrowLong', '做多')} · ↓ {t('eventContract.arrowShort', '做空')} · {t('eventContract.arrowNote', '收盘锁定·不重绘·下根开盘入场')}
          </span>
        </div>
        <EventContractChart exchange={exchange} symbol={chartSymbol} expiry={chartExpiry} />
      </div>

      <div className="mt-6 border rounded-lg p-4 bg-card">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <h3 className="font-semibold">{t('eventContract.history', '历史 K 线 (近一年走势)')}</h3>
          <select className="border rounded px-2 py-1 text-sm bg-background" value={chartSymbol} onChange={(e) => setChartSymbol(e.target.value)}>
            <option value="BTC">BTC</option><option value="ETH">ETH</option>
          </select>
          <span className="text-xs text-muted-foreground">{t('eventContract.historyNote', '日线 · 看大趋势与历史形态')}</span>
        </div>
        <HistoryChart exchange={exchange} symbol={chartSymbol} period="1d" limit={365} />
      </div>

      <div className="mt-6 border rounded-lg p-4 bg-card">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <h3 className="font-semibold">{t('eventContract.backtest', '历史回测对比')}</h3>
          <select className="border rounded px-2 py-1 text-sm bg-background" value={btSymbol} onChange={(e) => setBtSymbol(e.target.value)}>
            <option value="BTC">BTC</option><option value="ETH">ETH</option>
          </select>
          <select className="border rounded px-2 py-1 text-sm bg-background" value={btExpiry} onChange={(e) => setBtExpiry(Number(e.target.value))}>
            <option value={5}>5min</option><option value={10}>10min</option>
          </select>
          <button onClick={runBacktest} disabled={btLoading}
            className="px-3 py-1 text-sm rounded bg-primary text-primary-foreground disabled:opacity-50">
            {btLoading ? t('eventContract.running', '运行中…') : t('eventContract.run', '运行回测')}
          </button>
          <span className="text-xs text-muted-foreground">{t('eventContract.breakeven', '盈亏平衡胜率 ~55.6% (赔付0.8)')}</span>
        </div>
        {bt && (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b">
                  <th className="py-1">{t('eventContract.signal', '信号')}</th>
                  <th className="text-right">{t('eventContract.orders', '单数')}</th>
                  <th className="text-right">{t('eventContract.winRate', '胜率')}</th>
                  <th className="text-right">{t('eventContract.netPnl', '净收益')}</th>
                </tr>
              </thead>
              <tbody>
                {[...bt.order_flow, ...bt.ta]
                  .filter((r) => r.total >= 30)
                  .sort((a, b) => b.win_rate - a.win_rate)
                  .slice(0, 8)
                  .map((r, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1">{r.signal || r.strategy}</td>
                      <td className="text-right">{r.total}</td>
                      <td className={`text-right font-medium ${r.win_rate >= 0.556 ? 'text-green-500' : ''}`}>{(r.win_rate * 100).toFixed(1)}%</td>
                      <td className={`text-right ${r.net_pnl > 0 ? 'text-green-500' : 'text-red-500'}`}>{r.net_pnl.toFixed(1)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
