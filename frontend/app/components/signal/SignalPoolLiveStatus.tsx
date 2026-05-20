import type { TFunction } from 'i18next'
import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertCircle, RefreshCw } from 'lucide-react'
import { API_BASE, type SignalPool } from './SignalManagerSupport'

interface SignalRuntimeSignal {
  signal_id: number
  signal_name?: string
  metric?: string
  operator?: string
  threshold?: number | string | null
  time_window?: string
  current_value?: number | string | null
  condition_met?: boolean | null
  ratio?: number | null
  error?: string | null
}

interface SignalRuntimePool {
  pool_id: number
  pool_name?: string
  symbol: string
  logic: string
  is_active: boolean
  detector_active: boolean
  last_check_time?: string | null
  seconds_since_check?: number | null
  last_triggered_at?: string | null
  signals: SignalRuntimeSignal[]
}

interface SignalRuntimePayload {
  generated_at: string
  pools: SignalRuntimePool[]
}

interface SignalPoolLiveStatusProps {
  pool: SignalPool
  t: TFunction
}

export function SignalPoolLiveStatus({ pool, t }: SignalPoolLiveStatusProps) {
  const symbolsKey = pool.symbols.join(',')
  const [payload, setPayload] = useState<SignalRuntimePayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const url = useMemo(() => {
    const params = new URLSearchParams()
    params.set('exchange', pool.exchange || 'binance')
    params.set('pool_id', String(pool.id))
    if (symbolsKey) params.set('symbols', symbolsKey)
    return `${API_BASE}/live-state?${params.toString()}`
  }, [pool.exchange, pool.id, symbolsKey])

  useEffect(() => {
    if (pool.source_type === 'wallet_tracking') return
    let mounted = true
    let controller: AbortController | null = null

    const load = async () => {
      controller?.abort()
      controller = new AbortController()
      try {
        const res = await fetch(url, { signal: controller.signal })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (!mounted) return
        setPayload(data)
        setError(null)
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        if (mounted) setError((err as Error).message)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    load()
    const timer = window.setInterval(load, 15000)
    return () => {
      mounted = false
      controller?.abort()
      window.clearInterval(timer)
    }
  }, [pool.source_type, url])

  if (pool.source_type === 'wallet_tracking') return null

  const rows = payload?.pools || []
  return (
    <div className="rounded border bg-muted/30 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-medium">
          <Activity className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
          <span>{t('signals.liveStatus.title', 'Live Status')}</span>
        </div>
        <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
          <span>{payload ? formatTime(payload.generated_at) : '-'}</span>
        </div>
      </div>

      {error ? (
        <div className="flex items-center gap-1 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5" />
          <span>{t('signals.liveStatus.error', 'Live state unavailable')}: {error}</span>
        </div>
      ) : rows.length === 0 ? (
        <div className="text-xs text-muted-foreground">
          {loading ? t('signals.liveStatus.loading', 'Loading live state...') : t('signals.liveStatus.empty', 'No live state yet')}
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map(row => (
            <div key={`${row.pool_id}-${row.symbol}`} className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{row.symbol}</span>
                  <span className={row.is_active ? activeClass : inactiveClass}>
                    {row.is_active ? t('signals.liveStatus.met', 'MET') : t('signals.liveStatus.notMet', 'NOT MET')}
                  </span>
                </div>
                <span className="text-muted-foreground">
                  {t('signals.liveStatus.lastCheck', 'Last check')}: {formatAge(row.seconds_since_check)}
                </span>
              </div>
              <div className="grid gap-1.5">
                {row.signals.map(signal => (
                  <div key={signal.signal_id} className="flex items-center justify-between gap-2 rounded bg-background/70 px-2 py-1 text-xs">
                    <span className="min-w-0 truncate">
                      {signal.signal_name || signal.metric || signal.signal_id}
                    </span>
                    <span className="shrink-0 text-muted-foreground">
                      {formatSignalValue(signal)} / {formatCondition(signal)}
                    </span>
                    <span className={signal.condition_met ? activeClass : inactiveClass}>
                      {signal.condition_met ? t('signals.liveStatus.metShort', 'ON') : t('signals.liveStatus.offShort', 'OFF')}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const activeClass = 'shrink-0 rounded bg-green-500/15 px-1.5 py-0.5 text-[10px] font-medium text-green-700 dark:text-green-300'
const inactiveClass = 'shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground'

function formatSignalValue(signal: SignalRuntimeSignal): string {
  if (signal.error) return 'error'
  return formatNumber(signal.current_value ?? signal.ratio)
}

function formatCondition(signal: SignalRuntimeSignal): string {
  const threshold = signal.threshold ?? 'N/A'
  return `${signal.operator || 'event'} ${threshold}`
}

function formatNumber(value: unknown): string {
  if (typeof value === 'number') return Math.abs(value) >= 100 ? value.toFixed(2) : value.toFixed(5)
  if (typeof value === 'string' && value) return value
  return 'N/A'
}

function formatAge(seconds?: number | null): string {
  if (seconds == null) return 'N/A'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

function formatTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '-' : parsed.toLocaleTimeString()
}
