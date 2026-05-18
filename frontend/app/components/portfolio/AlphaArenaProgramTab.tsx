import type { Dispatch, ReactNode, SetStateAction } from 'react'
import type { TFunction } from 'i18next'
import type { ProgramExecutionLog } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { formatDateTime } from '@/lib/dateTime'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import FlipNumber from './FlipNumber'
import { getProgramIconColors } from './logoAssets'

interface AlphaArenaProgramTabProps {
  filterBar: ReactNode
  loading: boolean
  logs: ProgramExecutionLog[]
  totalLogsCount: number
  expandedLog: number | null
  copiedLog: number | null
  copiedSection: string | null
  hasMore: boolean
  isLoadingMore: boolean
  t: TFunction
  setExpandedLog: Dispatch<SetStateAction<number | null>>
  onCopyLog: (log: ProgramExecutionLog) => void
  onCopySection: (logId: number, section: string, data: unknown) => void
  onLoadMore: () => void
}

const formatDate = (value?: string | null) => formatDateTime(value, { style: 'short' })

export default function AlphaArenaProgramTab({
  filterBar,
  loading,
  logs,
  totalLogsCount,
  expandedLog,
  copiedLog,
  copiedSection,
  hasMore,
  isLoadingMore,
  t,
  setExpandedLog,
  onCopyLog,
  onCopySection,
  onLoadMore,
}: AlphaArenaProgramTabProps) {
  return (
    <>
      {filterBar}
      {loading && logs.length === 0 ? (
        <div className="text-xs text-muted-foreground">{t('feed.loadingProgram', 'Loading program executions...')}</div>
      ) : logs.length === 0 ? (
        <div className="text-xs text-muted-foreground">{t('feed.noProgram', 'No program executions yet.')}</div>
      ) : (
        logs.map((log) => {
          const isExpanded = expandedLog === log.id
          const iconColors = getProgramIconColors(log.program_id)

          return (
            <button
              key={log.id}
              type="button"
              className="w-full text-left border border-border rounded bg-muted/30 p-4 space-y-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setExpandedLog(current => current === log.id ? null : log.id)}
            >
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-wide text-muted-foreground">
                <div className="flex items-center gap-2">
                  <svg className="h-5 w-5 rounded-full" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
                    <path d="M508.416 3.584c-260.096 0-243.712 112.64-243.712 112.64l0.512 116.736h248.32v34.816H166.4S0 248.832 0 510.976s145.408 252.928 145.408 252.928h86.528v-121.856S227.328 496.64 374.784 496.64h246.272s138.24 2.048 138.24-133.632V139.776c-0.512 0 20.48-136.192-250.88-136.192zM371.712 82.432c24.576 0 44.544 19.968 44.544 44.544 0 24.576-19.968 44.544-44.544 44.544-24.576 0-44.544-19.968-44.544-44.544-0.512-24.576 19.456-44.544 44.544-44.544z" fill={iconColors.primary} />
                    <path d="M515.584 1022.464c260.096 0 243.712-112.64 243.712-112.64l-0.512-116.736H510.976V757.76h346.624s166.4 18.944 166.4-243.2-145.408-252.928-145.408-252.928h-86.528v121.856s4.608 145.408-142.848 145.408h-245.76s-138.24-2.048-138.24 133.632v224.768c0-0.512-20.992 135.168 250.368 135.168z m136.704-78.336c-24.576 0-44.544-19.968-44.544-44.544 0-24.576 19.968-44.544 44.544-44.544 24.576 0 44.544 19.968 44.544 44.544 0.512 24.576-19.456 44.544-44.544 44.544z" fill={iconColors.secondary} />
                  </svg>
                  <span className="font-semibold text-foreground">{log.program_name}</span>
                  <span className="text-muted-foreground">→</span>
                  <span className="text-foreground">{log.account_name}</span>
                </div>
                <span>{formatDate(log.created_at)}</span>
              </div>

              <div className="text-sm font-medium text-foreground flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-1 rounded text-xs font-bold ${
                    log.decision_action?.toUpperCase() === 'BUY'
                      ? 'bg-emerald-100 text-emerald-800'
                      : log.decision_action?.toUpperCase() === 'SELL'
                      ? 'bg-red-100 text-red-800'
                      : log.decision_action?.toUpperCase() === 'CLOSE'
                      ? 'bg-blue-100 text-blue-800'
                      : log.decision_action?.toUpperCase() === 'HOLD'
                      ? 'bg-gray-200 text-gray-800'
                      : 'bg-orange-100 text-orange-800'
                  }`}>
                    {(log.decision_action || 'UNKNOWN').toUpperCase()}
                  </span>
                  {log.decision_symbol && (
                    <span className="font-semibold">{log.decision_symbol}</span>
                  )}
                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                    log.trigger_type === 'signal'
                      ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400'
                      : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                  }`}>
                    {log.trigger_type === 'signal' ? t('feed.signalPoolTrigger', 'Signal Pool') : t('feed.scheduledTrigger', 'Scheduled')}
                  </span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                    log.success
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                  }`}>
                    {log.success ? t('common.success', 'Success') : t('common.failed', 'Failed')}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 px-1.5 py-0.5 rounded bg-slate-800/80">
                  <img
                    src={log.exchange === 'binance' ? '/static/binance_logo.svg' : '/static/hyperliquid_logo.svg'}
                    alt={log.exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
                    className="h-3.5 w-3.5"
                  />
                  <span className="text-[10px] font-medium text-slate-200">
                    {log.exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
                  </span>
                </div>
              </div>

              <div className="text-xs text-muted-foreground">
                {isExpanded ? log.decision_reason : `${(log.decision_reason || '').slice(0, 160)}${(log.decision_reason || '').length > 160 ? '…' : ''}`}
              </div>

              <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground uppercase tracking-wide">
                <span>{t('feed.equity', 'Equity')}: <span className="font-semibold text-foreground">
                  <FlipNumber value={log.market_context?.input_data?.total_equity || 0} prefix="$" decimals={2} />
                </span></span>
                <span>{t('feed.marginUsed', 'Margin')}: <span className="font-semibold text-foreground">{(log.market_context?.input_data?.margin_usage_percent || 0).toFixed(1)}%</span></span>
                <span>{t('feed.executed', 'Executed')}: <span className={`font-semibold ${log.success ? 'text-emerald-600' : 'text-red-600'}`}>{log.success ? 'YES' : 'NO'}</span></span>
              </div>

              {!isExpanded && (
                <div className="mt-2 text-[11px] text-primary underline">
                  {t('feed.clickExpand', 'Click to expand')}
                </div>
              )}

              {isExpanded && (() => {
                const ctx = log.market_context
                const inputData = ctx?.input_data
                const dataQueries = ctx?.data_queries || []
                const execLogs = ctx?.execution_logs || []

                return (
                  <div className="space-y-2 pt-3 border-t border-border/50" onClick={(e) => e.stopPropagation()}>
                    <Collapsible defaultOpen>
                      <div className="flex items-center justify-between">
                        <CollapsibleTrigger className="flex items-center gap-2 p-2 hover:bg-muted rounded text-sm font-medium">
                          <ChevronDown className="h-4 w-4" />
                          {t('feed.inputData', 'Input Data')}
                        </CollapsibleTrigger>
                        {inputData && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              onCopySection(log.id, 'input', inputData)
                            }}
                            className={`px-2 py-1 text-[10px] font-medium rounded transition-all ${
                              copiedSection === `${log.id}-input`
                                ? 'bg-emerald-500/20 text-emerald-600'
                                : 'bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground'
                            }`}
                          >
                            {copiedSection === `${log.id}-input` ? `✓ ${t('feed.copied', 'Copied')}` : t('feed.copy', 'Copy')}
                          </button>
                        )}
                      </div>
                      <CollapsibleContent className="pl-4 text-xs space-y-2 pb-2">
                        {inputData ? (
                          <>
                            <div className="space-y-1 p-2 bg-muted/50 rounded">
                              <div className="font-medium text-muted-foreground mb-1">{t('feed.basicInfo', 'Basic Info')}</div>
                              <div>{t('feed.environment', 'Environment')}: <span className="font-mono">{inputData.environment || 'N/A'}</span></div>
                              <div>{t('feed.trigger', 'Trigger')}: <span className="font-mono">{inputData.trigger_symbol || '(scheduled)'}</span> ({inputData.trigger_type})</div>
                              {inputData.signal_source_type && (
                                <div>{t('feed.source', 'Source')}: <span className="font-mono">{inputData.signal_source_type}</span></div>
                              )}
                              <div>{t('feed.balance', 'Balance')}: <span className="font-mono">${Number(inputData.available_balance || 0).toFixed(2)}</span></div>
                              <div>{t('feed.equity', 'Equity')}: <span className="font-mono">${Number(inputData.total_equity || 0).toFixed(2)}</span></div>
                              <div>{t('feed.marginUsed', 'Margin Used')}: <span className="font-mono">{Number(inputData.margin_usage_percent || 0).toFixed(1)}%</span></div>
                              <div>{t('feed.maxLeverage', 'Max Leverage')}: <span className="font-mono">{inputData.max_leverage || 'N/A'}</span></div>
                              <div>{t('feed.defaultLeverage', 'Default Leverage')}: <span className="font-mono">{inputData.default_leverage || 'N/A'}</span></div>
                            </div>

                            {inputData.trigger_type === 'signal' && (
                              <Collapsible>
                                <CollapsibleTrigger className="flex items-center gap-2 w-full p-2 hover:bg-muted rounded text-xs font-medium">
                                  <ChevronRight className="h-3 w-3" />
                                  {t('feed.signalContext', 'Signal Context')} ({inputData.signal_pool_name || inputData.signal_pool_id || 'N/A'})
                                </CollapsibleTrigger>
                                <CollapsibleContent className="pl-4 text-xs">
                                  <pre className="bg-muted p-2 rounded overflow-x-auto whitespace-pre-wrap">
{JSON.stringify({
  signal_pool_name: inputData.signal_pool_name,
  signal_pool_id: inputData.signal_pool_id,
  pool_logic: inputData.pool_logic,
  signal_source_type: inputData.signal_source_type,
  triggered_signals: inputData.triggered_signals,
  wallet_event: inputData.wallet_event,
}, null, 2)}
                                  </pre>
                                </CollapsibleContent>
                              </Collapsible>
                            )}

                            {inputData.trigger_market_regime && (
                              <Collapsible>
                                <CollapsibleTrigger className="flex items-center gap-2 w-full p-2 hover:bg-muted rounded text-xs font-medium">
                                  <ChevronRight className="h-3 w-3" />
                                  {t('feed.triggerRegime', 'Trigger Market Regime')} ({inputData.trigger_market_regime.regime})
                                </CollapsibleTrigger>
                                <CollapsibleContent className="pl-4 text-xs">
                                  <pre className="bg-muted p-2 rounded overflow-x-auto whitespace-pre-wrap">
{JSON.stringify(inputData.trigger_market_regime, null, 2)}
                                  </pre>
                                </CollapsibleContent>
                              </Collapsible>
                            )}

                            <Collapsible>
                              <CollapsibleTrigger className="flex items-center gap-2 w-full p-2 hover:bg-muted rounded text-xs font-medium">
                                <ChevronRight className="h-3 w-3" />
                                {t('feed.positions', 'Positions')} ({inputData.positions_count || Object.keys(inputData.positions || {}).length})
                              </CollapsibleTrigger>
                              <CollapsibleContent className="pl-4 text-xs">
                                <pre className="bg-muted p-2 rounded overflow-x-auto whitespace-pre-wrap">
{JSON.stringify(inputData.positions, null, 2)}
                                </pre>
                              </CollapsibleContent>
                            </Collapsible>

                            <Collapsible>
                              <CollapsibleTrigger className="flex items-center gap-2 w-full p-2 hover:bg-muted rounded text-xs font-medium">
                                <ChevronRight className="h-3 w-3" />
                                {t('feed.openOrders', 'Open Orders')} ({inputData.open_orders_count ?? (inputData.open_orders?.length || 0)})
                              </CollapsibleTrigger>
                              <CollapsibleContent className="pl-4 text-xs">
                                <pre className="bg-muted p-2 rounded overflow-x-auto whitespace-pre-wrap">
{JSON.stringify(inputData.open_orders, null, 2)}
                                </pre>
                              </CollapsibleContent>
                            </Collapsible>
                          </>
                        ) : (
                          <div className="text-muted-foreground">{t('feed.noInputData', 'No input data available')}</div>
                        )}
                      </CollapsibleContent>
                    </Collapsible>

                    {dataQueries.length > 0 && (
                      <Collapsible>
                        <div className="flex items-center justify-between">
                          <CollapsibleTrigger className="flex items-center gap-2 p-2 hover:bg-muted rounded text-sm font-medium">
                            <ChevronDown className="h-4 w-4" />
                            {t('feed.dataQueries', 'Data Queries')} ({dataQueries.length})
                          </CollapsibleTrigger>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              onCopySection(log.id, 'queries', dataQueries)
                            }}
                            className={`px-2 py-1 text-[10px] font-medium rounded transition-all ${
                              copiedSection === `${log.id}-queries`
                                ? 'bg-emerald-500/20 text-emerald-600'
                                : 'bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground'
                            }`}
                          >
                            {copiedSection === `${log.id}-queries` ? `✓ ${t('feed.copied', 'Copied')}` : t('feed.copy', 'Copy')}
                          </button>
                        </div>
                        <CollapsibleContent className="pl-6 text-xs space-y-2 max-h-48 overflow-y-auto pb-2">
                          {dataQueries.map((q, i) => (
                            <div key={i} className="p-2 bg-muted rounded">
                              <div className="font-mono text-primary">{q.method}({JSON.stringify(q.args)})</div>
                              <div className="text-muted-foreground mt-1 truncate">→ {JSON.stringify(q.result).slice(0, 100)}...</div>
                            </div>
                          ))}
                        </CollapsibleContent>
                      </Collapsible>
                    )}

                    {execLogs.length > 0 && (
                      <Collapsible>
                        <div className="flex items-center justify-between">
                          <CollapsibleTrigger className="flex items-center gap-2 p-2 hover:bg-muted rounded text-sm font-medium">
                            <ChevronDown className="h-4 w-4" />
                            {t('feed.executionLogs', 'Execution Logs')} ({execLogs.length})
                          </CollapsibleTrigger>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              onCopySection(log.id, 'logs', execLogs)
                            }}
                            className={`px-2 py-1 text-[10px] font-medium rounded transition-all ${
                              copiedSection === `${log.id}-logs`
                                ? 'bg-emerald-500/20 text-emerald-600'
                                : 'bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground'
                            }`}
                          >
                            {copiedSection === `${log.id}-logs` ? `✓ ${t('feed.copied', 'Copied')}` : t('feed.copy', 'Copy')}
                          </button>
                        </div>
                        <CollapsibleContent className="pl-6 text-xs font-mono bg-muted p-2 rounded max-h-32 overflow-y-auto">
                          {execLogs.map((line, i) => (
                            <div key={i}>{line}</div>
                          ))}
                        </CollapsibleContent>
                      </Collapsible>
                    )}

                    {(log.decision_json || log.error_message) && (
                      <Collapsible defaultOpen>
                        <CollapsibleTrigger className="flex items-center gap-2 w-full p-2 hover:bg-muted rounded text-sm font-medium">
                          <ChevronDown className="h-4 w-4" />
                          {log.success ? t('feed.decisionDetails', 'Decision Details') : t('common.error', 'Error')}
                        </CollapsibleTrigger>
                        <CollapsibleContent className="pl-6 text-xs pb-2">
                          <pre className={`p-2 rounded overflow-x-auto whitespace-pre-wrap ${
                            log.success ? 'bg-muted' : 'bg-red-50 dark:bg-red-900/20 text-red-600'
                          }`}>
                            {log.success
                              ? JSON.stringify(log.decision_json, null, 2)
                              : log.error_message}
                          </pre>
                        </CollapsibleContent>
                      </Collapsible>
                    )}

                    <div className="mt-3 flex justify-end">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          onCopyLog(log)
                        }}
                        className={`px-3 py-1.5 text-[10px] font-medium rounded transition-all ${
                          copiedLog === log.id
                            ? 'bg-emerald-500/20 text-emerald-600 border border-emerald-500/30'
                            : 'bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground border border-border/60'
                        }`}
                      >
                        {copiedLog === log.id ? `✓ ${t('feed.copied', 'Copied')}` : t('feed.copy', 'Copy')}
                      </button>
                    </div>
                  </div>
                )
              })()}

              {isExpanded && (
                <div className="mt-2 text-[11px] text-primary underline">
                  {t('feed.clickCollapse', 'Click to collapse')}
                </div>
              )}
            </button>
          )
        })
      )}

      {totalLogsCount > 0 && hasMore && (
        <div className="flex justify-center pt-4">
          <Button
            onClick={onLoadMore}
            disabled={isLoadingMore}
            variant="outline"
            size="sm"
            className="text-xs"
          >
            {isLoadingMore ? (
              <>
                <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                {t('feed.loading', 'Loading...')}
              </>
            ) : (
              t('feed.loadMore', 'Load More')
            )}
          </Button>
        </div>
      )}

      {totalLogsCount > 0 && !hasMore && (
        <div className="flex justify-center pt-4 text-xs text-muted-foreground">
          {t('feed.allLoaded', 'All history loaded')}
        </div>
      )}
    </>
  )
}
