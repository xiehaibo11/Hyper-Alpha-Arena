import type { TFunction } from 'i18next'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  ExchangeBadge,
  formatShortAddress,
  formatWalletActionLabel,
  formatWalletDirectionLabel,
  formatWalletEventType,
  formatWalletMetricValue,
  type SignalDefinition,
  type SignalPool,
  type SignalTriggerLog,
} from './SignalManagerSupport'
import SignalLogsHeader from './SignalLogsHeader'

interface SignalTriggerLogsTabProps {
  t: TFunction
  logs: SignalTriggerLog[]
  logsTotal: number
  pools: SignalPool[]
  signals: SignalDefinition[]
  watchlistSymbols: string[]
  logsFilterPool: number | null
  logsFilterSymbol: string
  onPoolChange: (poolId: number | null) => void
  onSymbolChange: (symbol: string) => void
  loadLogsWithFilters: (poolId?: number | null, symbol?: string) => void
  onLoadMore: () => void
}

export default function SignalTriggerLogsTab({
  t,
  logs,
  logsTotal,
  pools,
  signals,
  watchlistSymbols,
  logsFilterPool,
  logsFilterSymbol,
  onPoolChange,
  onSymbolChange,
  loadLogsWithFilters,
  onLoadMore,
}: SignalTriggerLogsTabProps) {
  return (
    <Card className="h-full flex flex-col">
      <SignalLogsHeader
        t={t}
        pools={pools}
        watchlistSymbols={watchlistSymbols}
        logsFilterPool={logsFilterPool}
        logsFilterSymbol={logsFilterSymbol}
        logsTotal={logsTotal}
        onPoolChange={onPoolChange}
        onSymbolChange={onSymbolChange}
        loadLogsWithFilters={loadLogsWithFilters}
      />
      <CardContent className="flex-1 overflow-hidden pt-2">
        {logs.length === 0 ? (
          <p className="text-muted-foreground text-center py-8">{t('signals.noTriggers', 'No triggers recorded yet')}</p>
        ) : (
          <ScrollArea className="h-[calc(100vh-280px)]">
            <div className="space-y-2">
              {logs.map(log => {
                const triggerData = log.trigger_value as Record<string, unknown> | null
                const timestamp = log.triggered_at.endsWith('Z') ? log.triggered_at : log.triggered_at + 'Z'
                const isWalletTrigger = Boolean(
                  log.pool_id &&
                  triggerData &&
                  triggerData.source_type === 'wallet_tracking'
                )
                const isPoolTrigger = log.pool_id && triggerData && 'logic' in triggerData
                const pool = log.pool_id ? pools.find(p => p.id === log.pool_id) : null
                const signal = log.signal_id ? signals.find(s => s.id === log.signal_id) : null
                const poolName = log.pool_id ? pool?.pool_name : null
                const signalName = signal?.signal_name
                const logExchange = pool?.exchange || signal?.exchange || 'hyperliquid'

                const formatTriggerDetails = () => {
                  if (!triggerData) return null
                  if (triggerData.source_type === 'wallet_tracking') {
                    const eventType = typeof triggerData.event_type === 'string'
                      ? formatWalletEventType(t, triggerData.event_type)
                      : t('signals.walletTracking.sourceTypeLabel', 'Wallet Tracking')
                    const address = typeof triggerData.address === 'string' ? triggerData.address : null
                    const summary = typeof triggerData.summary === 'string' ? triggerData.summary : null
                    const detail = (typeof triggerData.detail === 'object' && triggerData.detail && !Array.isArray(triggerData.detail))
                      ? triggerData.detail as Record<string, unknown>
                      : null
                    const action = typeof detail?.action === 'string'
                      ? formatWalletActionLabel(t, detail.action)
                      : null
                    const direction = typeof detail?.direction === 'string'
                      ? formatWalletDirectionLabel(t, detail.direction)
                      : null
                    const notionalValue = formatWalletMetricValue(detail?.notional_value)
                    const entryPrice = formatWalletMetricValue(detail?.entry_price, 4)
                    const leverage = formatWalletMetricValue(detail?.leverage)
                    const unrealizedPnl = formatWalletMetricValue(detail?.unrealized_pnl)
                    const liquidationPrice = formatWalletMetricValue(detail?.liquidation_price, 4)
                    const closedPnl = formatWalletMetricValue(detail?.closed_pnl)
                    const averagePrice = formatWalletMetricValue(detail?.average_price, 4)
                    return (
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="px-1.5 py-0.5 rounded text-xs bg-purple-500/20 text-purple-400">
                            {eventType}
                          </span>
                          {address && <span>{formatShortAddress(address)}</span>}
                        </div>
                        {summary && <div>{summary}</div>}
                        {(action || direction || notionalValue || entryPrice || leverage || unrealizedPnl || liquidationPrice || closedPnl || averagePrice) && (
                          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                            {action && (
                              <span>{t('signals.walletTracking.logAction', 'Action')}: <span className="text-foreground">{action}</span></span>
                            )}
                            {direction && (
                              <span>{t('signals.walletTracking.logDirection', 'Direction')}: <span className="text-foreground">{direction}</span></span>
                            )}
                            {notionalValue && (
                              <span>{t('signals.walletTracking.logNotional', 'Notional')}: <span className="text-foreground">${notionalValue}</span></span>
                            )}
                            {entryPrice && (
                              <span>{t('signals.walletTracking.logEntryPrice', 'Entry Price')}: <span className="text-foreground">{entryPrice}</span></span>
                            )}
                            {leverage && (
                              <span>{t('signals.walletTracking.logLeverage', 'Leverage')}: <span className="text-foreground">{leverage}</span></span>
                            )}
                            {unrealizedPnl && (
                              <span>{t('signals.walletTracking.logUnrealizedPnl', 'Unrealized PnL')}: <span className="text-foreground">${unrealizedPnl}</span></span>
                            )}
                            {liquidationPrice && (
                              <span>{t('signals.walletTracking.logLiquidationPrice', 'Liquidation Price')}: <span className="text-foreground">{liquidationPrice}</span></span>
                            )}
                            {closedPnl && (
                              <span>{t('signals.walletTracking.logClosedPnl', 'Closed PnL')}: <span className="text-foreground">${closedPnl}</span></span>
                            )}
                            {averagePrice && (
                              <span>{t('signals.walletTracking.logAveragePrice', 'Avg Price')}: <span className="text-foreground">{averagePrice}</span></span>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  }
                  if ('logic' in triggerData && 'signals_triggered' in triggerData) {
                    const logic = triggerData.logic as string
                    const triggeredSignals = triggerData.signals_triggered as Array<{
                      signal_name: string; metric: string; current_value?: number; threshold?: number;
                      direction?: string; volume?: number; volume_threshold?: number;
                    }>
                    return (
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className={`px-1.5 py-0.5 rounded text-xs ${logic === 'AND' ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'}`}>
                            {logic}
                          </span>
                          <span>Triggered signals:</span>
                        </div>
                        {triggeredSignals.map((s, i) => (
                          <div key={i} className="ml-4 text-xs">
                            {s.metric === 'taker_volume' ? (
                              <>• {s.signal_name}: {s.direction?.toUpperCase()} | ratio={s.current_value?.toFixed(2)} (≥{s.threshold}) | vol=${((s.volume || 0) / 1e6).toFixed(2)}M (≥${((s.volume_threshold || 0) / 1e6).toFixed(2)}M)</>
                            ) : s.metric === 'macd' ? (
                              <>• {s.signal_name}: {s.triggered_event} | MACD={s.values?.macd?.toFixed(4)} | Hist={s.values?.histogram?.toFixed(4)}</>
                            ) : (
                              <>• {s.signal_name}: {s.metric} = {s.current_value?.toFixed(4)} (threshold: {s.threshold})</>
                            )}
                          </div>
                        ))}
                      </div>
                    )
                  }
                  if ('direction' in triggerData && 'ratio' in triggerData) {
                    const dir = triggerData.direction as string
                    const ratio = (triggerData.ratio as number)?.toFixed(2)
                    const ratioThreshold = (triggerData.ratio_threshold as number) || 1.5
                    const buy = (triggerData.buy as number) || 0
                    const sell = (triggerData.sell as number) || 0
                    const totalVol = (buy + sell).toLocaleString()
                    const volThreshold = ((triggerData.volume_threshold as number) || 0).toLocaleString()
                    return `${dir.toUpperCase()} | Ratio: ${ratio} (≥${ratioThreshold}) | Vol: $${totalVol} (≥$${volThreshold})`
                  }
                  if ('metric' in triggerData && 'value' in triggerData) {
                    const val = (triggerData.value as number)?.toFixed(4)
                    return `${triggerData.metric}: ${val} ${triggerData.operator} ${triggerData.threshold}`
                  }
                  return null
                }

                return (
                  <div key={log.id} className="p-3 bg-muted rounded">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-primary">{log.symbol}</span>
                        <ExchangeBadge exchange={logExchange} size="xs" />
                        {isWalletTrigger || isPoolTrigger ? (
                          <span className="text-sm px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded">
                            Pool: {poolName || `#${log.pool_id}`}
                          </span>
                        ) : (
                          <span className="text-sm">{signalName || `Signal #${log.signal_id}`}</span>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {new Date(timestamp).toLocaleString()}
                      </span>
                    </div>
                    {triggerData && (
                      <div className="text-xs text-muted-foreground mt-1">
                        {formatTriggerDetails()}
                      </div>
                    )}
                    {log.market_regime && (
                      <div className="text-xs mt-1 flex items-center gap-2">
                        <span className={`px-1.5 py-0.5 rounded ${
                          log.market_regime.regime === 'breakout' ? 'bg-green-500/20 text-green-400' :
                          log.market_regime.regime === 'continuation' ? 'bg-blue-500/20 text-blue-400' :
                          log.market_regime.regime === 'absorption' ? 'bg-yellow-500/20 text-yellow-400' :
                          log.market_regime.regime === 'stop_hunt' ? 'bg-red-500/20 text-red-400' :
                          log.market_regime.regime === 'trap' ? 'bg-orange-500/20 text-orange-400' :
                          log.market_regime.regime === 'exhaustion' ? 'bg-purple-500/20 text-purple-400' :
                          'bg-gray-500/20 text-gray-400'
                        }`}>
                          {log.market_regime.regime.toUpperCase()}
                        </span>
                        <span className={log.market_regime.direction === 'bullish' ? 'text-green-400' : 'text-red-400'}>
                          {log.market_regime.direction}
                        </span>
                        <span className="text-muted-foreground">
                          conf: {(log.market_regime.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    )}
                  </div>
                )
              })}
              {logs.length < logsTotal && (
                <div className="flex justify-center pt-2">
                  <Button variant="outline" size="sm" onClick={onLoadMore}>
                    {t('signals.loadMore', 'Load More')} ({logs.length}/{logsTotal})
                  </Button>
                </div>
              )}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )
}
