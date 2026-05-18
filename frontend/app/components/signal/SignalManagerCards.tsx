import type { TFunction } from 'i18next'
import { CircleHelp, Edit, Eye, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  ExchangeBadge,
  MACD_EVENT_TYPES,
  METRICS,
  OPERATORS,
  formatWalletEventType,
  type SignalDefinition,
  type SignalPool,
  type TriggerCondition,
} from './SignalManagerSupport'

function formatCondition(cond: TriggerCondition) {
  const metric = cond.metric?.startsWith('factor:')
    ? `⚗ ${cond.metric.split(':')[1]}`
    : METRICS.find(m => m.value === cond.metric)?.label || cond.metric
  if (cond.metric === 'taker_volume') {
    const dir = (cond as any).direction || 'any'
    const ratio = (cond as any).ratio_threshold || 1.5
    const vol = ((cond as any).volume_threshold || 0).toLocaleString()
    return `${metric} | ${dir.toUpperCase()} ≥${ratio} Vol≥$${vol} (${cond.time_window})`
  }
  if (cond.metric === 'macd') {
    const events = (cond as any).event_types || []
    const eventLabels = events.map((event: string) => {
      const found = MACD_EVENT_TYPES.find(m => m.value === event)
      return found ? found.label : event
    }).join(', ')
    return `${metric} | ${eventLabels || 'No events'} (${cond.time_window})`
  }
  const op = OPERATORS.find(o => o.value === cond.operator)?.label || cond.operator
  return `${metric} ${op} ${cond.threshold} (${cond.time_window})`
}

interface SignalDefinitionCardProps {
  signal: SignalDefinition
  t: TFunction
  onEdit: (signal: SignalDefinition) => void
  onDelete: (signalId: number) => void
  onBacktest: (signal: SignalDefinition) => void
}

export function SignalDefinitionCard({ signal, t, onEdit, onDelete, onBacktest }: SignalDefinitionCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">{signal.signal_name}</CardTitle>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => onEdit(signal)}>
              <Edit className="w-4 h-4" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onDelete(signal.id)}>
              <Trash2 className="w-4 h-4 text-destructive" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground mb-2">{signal.description}</p>
        <p className="text-sm font-mono bg-muted p-2 rounded">
          {formatCondition(signal.trigger_condition)}
        </p>
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${signal.enabled ? 'bg-green-500' : 'bg-gray-400'}`} />
            <span className="text-xs">{signal.enabled ? t('signals.enabled', 'Enabled') : t('signals.disabled', 'Disabled')}</span>
            <ExchangeBadge exchange={signal.exchange || 'hyperliquid'} size="xs" />
          </div>
          <Button variant="outline" size="sm" onClick={() => onBacktest(signal)}>
            <Eye className="w-4 h-4 mr-1" />{t('signals.backtest', 'Backtest')}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

interface SignalPoolCardProps {
  pool: SignalPool
  signals: SignalDefinition[]
  watchlistSymbols: string[]
  t: TFunction
  onEdit: (pool: SignalPool) => void
  onDelete: (poolId: number) => void
  onBacktest: (pool: SignalPool, symbol: string) => void
}

export function SignalPoolCard({
  pool,
  signals,
  watchlistSymbols,
  t,
  onEdit,
  onDelete,
  onBacktest,
}: SignalPoolCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">{pool.pool_name}</CardTitle>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => onEdit(pool)}>
              <Edit className="w-4 h-4" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onDelete(pool.id)}>
              <Trash2 className="w-4 h-4 text-destructive" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground">
              {pool.source_type === 'wallet_tracking'
                ? t('signals.walletTracking.sourceTypeLabel', 'Wallet Tracking')
                : t('signals.dialog.marketSignalsType', 'Market Signals')}
            </span>
          </div>
          {pool.source_type === 'wallet_tracking' ? (
            <>
              <div>
                <span className="text-sm font-medium">{t('signals.walletTracking.addresses', 'Tracked Wallets')}: </span>
                <span className="text-sm">
                  {pool.source_config?.addresses?.join(', ') || t('signals.walletTracking.noneSelected', 'None selected')}
                </span>
              </div>
              <div>
                <span className="text-sm font-medium">{t('signals.walletTracking.eventTypes', 'Event Types')}: </span>
                <span className="text-sm">
                  {(pool.source_config?.event_types || []).length
                    ? (pool.source_config?.event_types || []).map(eventType => formatWalletEventType(t, eventType)).join(', ')
                    : t('signals.walletTracking.noneSelected', 'None selected')}
                </span>
              </div>
            </>
          ) : (
            <>
              <div>
                <span className="text-sm font-medium">{t('signals.symbols', 'Symbols')}: </span>
                <span className="text-sm">{pool.symbols.join(', ') || 'None'}</span>
              </div>
              <div>
                <span className="text-sm font-medium">{t('signals.tabs.signals', 'Signals')}: </span>
                <span className="text-sm">
                  {pool.signal_ids.map(id => signals.find(s => s.id === id)?.signal_name).filter(Boolean).join(', ') || 'None'}
                </span>
              </div>
            </>
          )}
          {pool.source_type !== 'wallet_tracking' && (
            <div>
              <span className="text-sm font-medium">{t('signals.logic', 'Logic')}: </span>
              <span className={`text-sm px-2 py-0.5 rounded ${pool.logic === 'AND' ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'}`}>
                {pool.logic || 'OR'}
              </span>
              <span className="text-xs text-muted-foreground ml-2">
                {pool.logic === 'AND' ? `(${t('signals.allSignalsTrigger', 'All signals must trigger')})` : `(${t('signals.anySignalTriggers', 'Any signal triggers')})`}
              </span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${pool.enabled ? 'bg-green-500' : 'bg-gray-400'}`} />
              <span className="text-xs">{pool.enabled ? t('signals.enabled', 'Enabled') : t('signals.disabled', 'Disabled')}</span>
              <ExchangeBadge exchange={pool.exchange || 'hyperliquid'} size="xs" />
            </div>
            {pool.source_type === 'wallet_tracking' ? (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button variant="outline" size="sm" disabled>
                        <Eye className="w-4 h-4 mr-1" />
                        {t('signals.backtest', 'Backtest')}
                        <CircleHelp className="w-3.5 h-3.5 ml-1 opacity-70" />
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-[260px] p-3">
                    <p className="text-xs">{t('signals.walletTracking.backtestHint', 'Wallet signals come from real-time external events and are not available for historical replay backtesting in the current version.')}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onBacktest(pool, watchlistSymbols[0] || 'BTC')}
                disabled={pool.signal_ids.length === 0}
              >
                <Eye className="w-4 h-4 mr-1" />
                {t('signals.backtest', 'Backtest')}
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
