import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import TradingViewChart from '@/components/klines/TradingViewChart'
import { pollAiStream } from '@/lib/pollAiStream'
import { formatDateTime, localToUtcTimestamp } from '@/lib/dateTime'
import {
  type LargeOrderZoneItem,
  type MarketFlowSummaryItem,
  type NewsArticle,
  startHyperAiInsightAnalysis,
} from '@/lib/api'
import {
  AnimatedMetricValue,
  BreakdownBars,
  DriverCard,
  FlowEventIcon,
  InsightEmptyState,
  InsightRefreshBadge,
  PriceRangeBar,
  ReactionChip,
  SentimentGauge,
  buildEvents,
  domainLabel,
  formatBucketLabel,
  formatCompactUsd,
  formatPercent,
  formatReactionAtOffset,
  getBucketStart,
  getNetFlowPresentation,
  getPeriodWindowMs,
  getSentimentTheme,
  normalizeRatio,
  parseStructuredInsight,
  type InsightAiState,
  type InsightChartPoint,
  type InsightEvent,
  type InsightExchange,
  type InsightPeriod,
  type InsightWindow,
  type StructuredAiInsight,
} from './DashboardInsightViewSupport'

export default function DashboardInsightView() {
  const { t, i18n } = useTranslation()
  const [selectedExchange, setSelectedExchange] = useState<InsightExchange>('binance')
  const [selectedSymbol, setSelectedSymbol] = useState('BTC')
  const [selectedPeriod, setSelectedPeriod] = useState<InsightPeriod>('1h')
  const analysisWindow: InsightWindow = '4h'
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>([])
  const [summary, setSummary] = useState<MarketFlowSummaryItem | null>(null)
  const [newsItems, setNewsItems] = useState<NewsArticle[]>([])
  const [zoneItems, setZoneItems] = useState<LargeOrderZoneItem[]>([])
  const [chartContext, setChartContext] = useState<InsightChartPoint[]>([])
  const [klineRefreshToken, setKlineRefreshToken] = useState(0)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [recentEventIds, setRecentEventIds] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  const [aiInsightEnabled, setAiInsightEnabled] = useState(false)
  const [aiState, setAiState] = useState<InsightAiState>('idle')
  const [aiResult, setAiResult] = useState('')
  const [aiInsight, setAiInsight] = useState<StructuredAiInsight | null>(null)
  const [aiGeneratedAt, setAiGeneratedAt] = useState<number | null>(null)
  const [aiStatusText, setAiStatusText] = useState('')
  const [aiError, setAiError] = useState('')
  const [completedSignature, setCompletedSignature] = useState('')

  const activeTaskRef = useRef(false)
  const analysisSeqRef = useRef(0)
  const previousEventIdsRef = useRef<string[]>([])
  const latestEventSignatureRef = useRef('')

  useEffect(() => {
    const loadWatchlist = async () => {
      const endpoint = selectedExchange === 'binance'
        ? '/api/binance/symbols/watchlist'
        : selectedExchange === 'okx'
          ? '/api/okx/symbols/watchlist'
          : '/api/hyperliquid/symbols/watchlist'
      const response = await fetch(endpoint)
      const data = await response.json()
      const symbols = data.symbols || []
      setWatchlistSymbols(symbols)
      if (symbols.length > 0 && !symbols.includes(selectedSymbol)) {
        setSelectedSymbol(symbols[0])
      }
    }

    loadWatchlist().catch(() => {
      setWatchlistSymbols([])
    })
  }, [selectedExchange, selectedSymbol])

  useEffect(() => {
    return () => {
      setAiInsightEnabled(false)
      setAiState('idle')
    }
  }, [])

  useEffect(() => {
    if (!selectedSymbol) return

    setLoading(true)
    const params = new URLSearchParams({
      symbol: selectedSymbol,
      exchange: selectedExchange,
      timeframe: selectedPeriod,
      window: analysisWindow,
    })
    const source = new EventSource(`/api/market-intelligence/stream?${params.toString()}`)

    const applyPayload = (payload: any) => {
      setSummary(payload?.summary || null)
      setNewsItems(Array.isArray(payload?.news_items) ? payload.news_items : [])
      setZoneItems(Array.isArray(payload?.zone_items) ? payload.zone_items : [])
      setLoading(false)
    }

    source.addEventListener('snapshot', (event) => {
      try {
        applyPayload(JSON.parse((event as MessageEvent).data))
      } catch (error) {
        console.error('Failed to parse market intelligence snapshot:', error)
      }
    })

    source.addEventListener('update', (event) => {
      try {
        applyPayload(JSON.parse((event as MessageEvent).data))
        setKlineRefreshToken(value => value + 1)
      } catch (error) {
        console.error('Failed to parse market intelligence update:', error)
      }
    })

    source.addEventListener('error', () => {
      setLoading(false)
    })

    return () => {
      source.close()
    }
  }, [analysisWindow, selectedExchange, selectedPeriod, selectedSymbol])

  const events = useMemo(
    () => buildEvents(t, newsItems, zoneItems, chartContext, selectedExchange, selectedSymbol, selectedPeriod),
    [chartContext, newsItems, selectedExchange, selectedPeriod, selectedSymbol, t, zoneItems]
  )

  useEffect(() => {
    const nextIds = events.map(event => event.id)
    const previousIds = previousEventIdsRef.current
    if (previousIds.length > 0) {
      const newlyInserted = nextIds.filter(id => !previousIds.includes(id))
      if (newlyInserted.length > 0) {
        setRecentEventIds(newlyInserted)
        const timer = window.setTimeout(() => setRecentEventIds([]), 1400)
        return () => window.clearTimeout(timer)
      }
    }
    previousEventIdsRef.current = nextIds
  }, [events])

  useEffect(() => {
    previousEventIdsRef.current = events.map(event => event.id)
    if (!selectedEventId && events.length > 0) {
      setSelectedEventId(events[0].id)
    }
  }, [events, selectedEventId])

  const selectedEvent = events.find(item => item.id === selectedEventId) || events[0] || null
  const eventBucketMs = getPeriodWindowMs(selectedPeriod)
  const fallbackFocusTime = chartContext.length > 0
    ? chartContext[chartContext.length - 1].time * 1000
    : Date.now()
  const focusedBucketStart = getBucketStart(selectedEvent?.time || fallbackFocusTime, eventBucketMs)
  const focusedEvents = useMemo(
    () => events.filter(event => getBucketStart(event.time, eventBucketMs) === focusedBucketStart),
    [eventBucketMs, events, focusedBucketStart]
  )
  const focusedFlowEvents = useMemo(
    () => focusedEvents.filter(event => event.kind === 'flow'),
    [focusedEvents]
  )
  const focusedNewsEvents = useMemo(
    () => focusedEvents.filter(event => event.kind === 'news'),
    [focusedEvents]
  )
  const focusedBucketLabel = useMemo(() => {
    const start = focusedBucketStart
    const end = focusedBucketStart + eventBucketMs
    return formatBucketLabel(start, end)
  }, [eventBucketMs, focusedBucketStart])

  const chartMarkers = useMemo(() => {
    const newsMarkers = newsItems.map(item => ({
      id: `news-${item.id}`,
      kind: 'news' as const,
      iconVariant: 'news' as const,
      time: item.published_at ? new Date(`${item.published_at}Z`).getTime() : Date.now(),
      position: 'aboveBar' as const,
      color: item.sentiment === 'bearish' ? '#f97316' : item.sentiment === 'bullish' ? '#0ea5e9' : '#94a3b8',
      shape: 'circle' as const,
      title: item.title,
      summary: item.ai_summary || item.summary || '',
      tone: item.sentiment === 'bullish' || item.sentiment === 'bearish' ? item.sentiment : 'mixed',
      metadata: [
        domainLabel(item.source_domain),
        item.symbols.slice(0, 3).join(', ') || t('dashboard.insight.watchlist', 'watchlist'),
      ],
    }))

    const zoneMarkers = zoneItems
      .filter(item => Math.abs(item.large_order_net) >= 100_000)
      .map(item => ({
        id: `flow-${item.time}-${item.large_order_net >= 0 ? 'up' : 'down'}`,
        kind: 'flow' as const,
        iconVariant: item.large_order_net >= 0 ? 'flow-up' as const : 'flow-down' as const,
        time: item.time,
        position: item.large_order_net >= 0 ? 'belowBar' as const : 'aboveBar' as const,
        color: item.large_order_net >= 0 ? '#16a34a' : '#dc2626',
        shape: item.large_order_net >= 0 ? 'arrowUp' as const : 'arrowDown' as const,
        title: item.large_order_net >= 0
          ? t('dashboard.insight.events.largeBuyTitle', 'Large buy flow expanded')
          : t('dashboard.insight.events.largeSellTitle', 'Large sell flow expanded'),
        summary: t(
          'dashboard.insight.events.flowSummary',
          `${selectedExchange} ${selectedSymbol} ${selectedPeriod} large net ${formatCompactUsd(item.large_order_net)}, buy/sell count ${item.large_buy_count}/${item.large_sell_count}.`,
          {
            exchange: selectedExchange,
            symbol: selectedSymbol,
            period: selectedPeriod,
            value: formatCompactUsd(item.large_order_net),
            buy_count: item.large_buy_count,
            sell_count: item.large_sell_count,
          }
        ),
        tone: item.large_order_net >= 0 ? 'bullish' as const : 'bearish' as const,
        metadata: [
          t('dashboard.insight.events.largeNet', `Large net: ${formatCompactUsd(item.large_order_net)}`, {
            value: formatCompactUsd(item.large_order_net),
          }),
          t('dashboard.insight.events.buySellCount', `Buy/Sell count: ${item.large_buy_count}/${item.large_sell_count}`, {
            buy_count: item.large_buy_count,
            sell_count: item.large_sell_count,
          }),
        ],
      }))

    return [...newsMarkers, ...zoneMarkers]
  }, [newsItems, selectedExchange, selectedPeriod, selectedSymbol, t, zoneItems])

  const latestEventSignature = useMemo(() => {
    const latestEvent = events[0]
    return `${selectedExchange}:${selectedSymbol}:${selectedPeriod}:${latestEvent?.id || 'none'}`
  }, [events, selectedExchange, selectedPeriod, selectedSymbol])

  useEffect(() => {
    latestEventSignatureRef.current = latestEventSignature
  }, [latestEventSignature])

  const aiContext = useMemo(() => {
    const cutoff = Date.now() - 4 * 3600_000
    return {
      exchange: selectedExchange,
      symbol: selectedSymbol,
      analysis_window: analysisWindow,
      chart_interval: selectedPeriod,
      chart: chartContext.filter(item => item.time * 1000 >= cutoff),
      summary,
      news: newsItems.filter(item => {
        if (!item.published_at) return false
        return new Date(`${item.published_at}Z`).getTime() >= cutoff
      }),
      large_order_zones: zoneItems.filter(item => item.time >= cutoff),
    }
  }, [analysisWindow, chartContext, newsItems, selectedExchange, selectedPeriod, selectedSymbol, summary, zoneItems])

  const runInsightAnalysis = async (signature: string) => {
    analysisSeqRef.current += 1
    const seq = analysisSeqRef.current
    activeTaskRef.current = true
    setAiState('thinking')
    setAiStatusText('')
    setAiError('')

    try {
      const data = await startHyperAiInsightAnalysis({
        context: aiContext,
        selected_event: selectedEvent ? {
          id: selectedEvent.id,
          kind: selectedEvent.kind,
          time: selectedEvent.time,
          title: selectedEvent.title,
          summary: selectedEvent.summary,
          tone: selectedEvent.tone,
          evidence: selectedEvent.evidence,
        } : null,
        lang: i18n.language?.startsWith('zh') ? 'zh' : 'en',
      })

      if (!data.task_id) {
        throw new Error('Failed to start Hyper AI insight analysis')
      }

      let content = ''
      const pollResult = await pollAiStream(data.task_id, {
        interval: 300,
        onChunk: (chunk) => {
          if (seq !== analysisSeqRef.current) return
          const eventType = chunk.event_type
          const eventData = chunk.data || {}

          if (eventType === 'content') {
            const delta = typeof eventData.text === 'string' ? eventData.text : typeof eventData.content === 'string' ? eventData.content : ''
            if (delta) {
              content += delta
              setAiResult(content)
            }
          } else if (eventType === 'reasoning' && eventData.content) {
            setAiStatusText(String(eventData.content).slice(0, 120))
          } else if (eventType === 'tool_call' && eventData.name) {
            setAiStatusText(`${String(eventData.name)}...`)
          } else if (eventType === 'error' && eventData.message) {
            setAiError(String(eventData.message))
          }
        },
      })

      if (seq !== analysisSeqRef.current) return

      if (pollResult.status === 'completed') {
        const finalContent = content || String(pollResult.result?.content || '')
        const parsedInsight = parseStructuredInsight(finalContent)
        if (!finalContent.trim()) {
          setAiState('error')
          setAiError(t('dashboard.insight.aiEmpty', 'Hyper AI returned no readable content.'))
        } else if (!parsedInsight) {
          setAiState('error')
          setAiError(t('dashboard.insight.aiInvalidFormat', 'Hyper AI returned an invalid insight format.'))
        } else {
          setAiResult(finalContent.trim())
          setAiInsight(parsedInsight)
          setAiGeneratedAt(Date.now())
          setAiState('ready')
          setCompletedSignature(latestEventSignatureRef.current || signature)
        }
      } else {
        setAiState('error')
        setAiError(pollResult.error || t('dashboard.insight.aiFailed', 'Hyper AI analysis failed.'))
        setCompletedSignature(latestEventSignatureRef.current || signature)
      }
    } catch (error) {
      if (seq !== analysisSeqRef.current) return
      setAiState('error')
      setAiError(error instanceof Error ? error.message : String(error))
      setCompletedSignature(latestEventSignatureRef.current || signature)
    } finally {
      if (seq === analysisSeqRef.current) {
        activeTaskRef.current = false
      }
    }
  }

  useEffect(() => {
    if (!aiInsightEnabled) {
      setAiState('idle')
      setAiError('')
      setAiStatusText('')
      return
    }

    if (activeTaskRef.current) return

    if (!latestEventSignature || latestEventSignature === completedSignature) {
      setAiState(aiInsight ? 'ready' : 'monitoring')
      return
    }

    runInsightAnalysis(latestEventSignature)
  }, [aiContext, aiInsight, aiInsightEnabled, completedSignature, i18n.language, latestEventSignature])

  const aiTheme = getSentimentTheme(aiInsight?.sentiment || 'mixed')
  const latestChartPrice = chartContext[chartContext.length - 1]?.close ?? null
  const showRefreshBadge = aiInsightEnabled && aiState === 'thinking' && !!aiInsight
  const showInlineError = aiState === 'error' && !aiInsight
  const netFlowDisplay = getNetFlowPresentation(
    t,
    summary?.net_inflow,
    'dashboard.insight.netInflow',
    'Net Inflow',
    'dashboard.insight.netOutflow',
    'Net Outflow'
  )
  const largeFlowDisplay = getNetFlowPresentation(
    t,
    summary?.large_order_net,
    'dashboard.insight.largeOrderInflow',
    'Large Order Inflow',
    'dashboard.insight.largeOrderOutflow',
    'Large Order Outflow'
  )
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-4 lg:grid-cols-3">
      <style>{`
        @keyframes insight-card-in {
          0% { opacity: 0; transform: translateY(-14px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes metric-flip-in {
          0% { opacity: 0; transform: translateY(10px) scale(0.98); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>

      <div className="lg:col-span-2 flex min-h-0 flex-col gap-4">
        <Card className="flex-1 min-h-[420px] overflow-hidden">
          <CardHeader className="space-y-3 py-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                    {t('dashboard.insight.exchange', 'Exchange')}
                  </div>
                  <Select value={selectedExchange} onValueChange={(value) => setSelectedExchange(value as InsightExchange)}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="hyperliquid">Hyperliquid</SelectItem>
                      <SelectItem value="binance">Binance</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                    {t('dashboard.insight.symbol', 'Symbol')}
                  </div>
                  <Select value={selectedSymbol} onValueChange={setSelectedSymbol}>
                    <SelectTrigger className="w-[120px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {watchlistSymbols.map(symbol => (
                        <SelectItem key={symbol} value={symbol}>{symbol}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                    {t('dashboard.insight.chartInterval', 'Chart Interval')}
                  </div>
                  <Select value={selectedPeriod} onValueChange={(value) => setSelectedPeriod(value as InsightPeriod)}>
                    <SelectTrigger className="w-[132px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="5m">5m</SelectItem>
                      <SelectItem value="15m">15m</SelectItem>
                      <SelectItem value="1h">1h</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 xl:grid-cols-5">
              <div className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{netFlowDisplay.label}</div>
                <div className={`mt-1 text-base font-semibold ${netFlowDisplay.className}`}>
                  <AnimatedMetricValue value={netFlowDisplay.value} />
                </div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{largeFlowDisplay.label}</div>
                <div className={`mt-1 text-base font-semibold ${largeFlowDisplay.className}`}>
                  <AnimatedMetricValue value={largeFlowDisplay.value} />
                </div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  {t('dashboard.insight.totalInflow', 'Total Inflow')}
                </div>
                <div className="mt-1 text-base font-semibold text-emerald-600">
                  <AnimatedMetricValue value={formatCompactUsd(summary?.total_buy_notional)} />
                </div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  {t('dashboard.insight.totalOutflow', 'Total Outflow')}
                </div>
                <div className="mt-1 text-base font-semibold text-red-600">
                  <AnimatedMetricValue value={formatCompactUsd(summary?.total_sell_notional)} />
                </div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{t('dashboard.insight.oiFunding', 'OI / Funding')}</div>
                <div className="mt-1 text-sm font-semibold text-foreground">
                  <AnimatedMetricValue value={`${formatPercent(summary?.open_interest_change_pct)} / ${formatPercent(summary?.funding_rate_pct, 4)}`} />
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="h-[calc(100%-8.25rem)] pb-4">
            <TradingViewChart
              symbol={selectedSymbol}
              period={selectedPeriod}
              exchange={selectedExchange}
              chartType="candlestick"
              selectedIndicators={[]}
              selectedFlowIndicators={[]}
              onLoadingChange={() => {}}
              onIndicatorLoadingChange={() => {}}
              onDataUpdate={(klines) => {
                setChartContext(Array.isArray(klines)
                  ? klines.map(item => ({ ...item, time: localToUtcTimestamp(Number(item.time || 0)) }))
                  : [])
              }}
              showVolumePane={false}
              eventMarkers={chartMarkers}
              activeEventMarkerId={selectedEventId || undefined}
              onEventMarkerClick={(eventId) => setSelectedEventId(eventId)}
              incrementalRefreshToken={klineRefreshToken}
            />
          </CardContent>
        </Card>

        <Card className="h-[324px] overflow-hidden">
          <CardHeader className="py-3">
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-sm">{t('dashboard.insight.newsTitle', 'News and Whale Flow')}</CardTitle>
              <div className="text-[11px] text-muted-foreground">{focusedBucketLabel}</div>
            </div>
          </CardHeader>
          <CardContent className="h-full overflow-hidden">
            <div className="grid h-full min-h-0 gap-4 lg:grid-cols-[minmax(260px,320px)_minmax(0,1fr)]">
              <div className="flex min-h-0 flex-col">
                <div className="pb-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  {t('dashboard.insight.whaleFlowTitle', 'Whale Flow')}
                </div>
                <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
                  {focusedFlowEvents.map(event => {
                    const reaction15m = formatReactionAtOffset(chartContext, event.time, 15 * 60 * 1000)
                    const reaction1h = formatReactionAtOffset(chartContext, event.time, 60 * 60 * 1000)

                    return (
                      <button
                        key={event.id}
                        type="button"
                        onClick={() => setSelectedEventId(event.id)}
                        className={`w-full rounded-xl border p-3 text-left transition-all duration-300 ${selectedEventId === event.id ? 'border-sky-300 bg-sky-50 shadow-sm' : 'border-border bg-background hover:bg-muted/50'} ${recentEventIds.includes(event.id) ? 'ring-2 ring-sky-200' : ''}`}
                        style={recentEventIds.includes(event.id) ? { animation: 'insight-card-in 360ms ease-out' } : undefined}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                              event.iconVariant === 'flow-down'
                                ? 'bg-red-50 text-red-600'
                                : 'bg-emerald-50 text-emerald-600'
                            }`}>
                              <FlowEventIcon direction={event.iconVariant === 'flow-down' ? 'down' : 'up'} />
                            </div>
                            <div className="line-clamp-2 text-sm font-medium text-foreground">{event.title}</div>
                          </div>
                          <div className="shrink-0 text-[11px] text-muted-foreground">
                            {formatDateTime(event.time, { style: 'short' })}
                          </div>
                        </div>
                        <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{event.summary}</div>
                        <div className="mt-2 space-y-1.5 text-[10px] text-muted-foreground">
                          <div className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap">
                            {event.evidence.slice(0, 2).map((item, index) => (
                              <span
                                key={`${event.id}-${index}`}
                                className="max-w-[140px] truncate rounded-full bg-muted px-1.5 py-0.5"
                              >
                                {item}
                              </span>
                            ))}
                          </div>
                          <div className="flex items-center gap-1.5 whitespace-nowrap">
                            <ReactionChip label={t('dashboard.insight.after15m', '15m later')} value={reaction15m} compact />
                            <ReactionChip label={t('dashboard.insight.after1h', '1h later')} value={reaction1h} compact />
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="flex min-h-0 flex-col">
                <div className="pb-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  {t('dashboard.insight.newsFeedTitle', 'News')}
                </div>
                <div className="min-h-0 overflow-y-auto pr-1">
                  <div className="grid gap-3 md:grid-cols-2">
                    {focusedNewsEvents.map(event => {
                      const reaction15m = formatReactionAtOffset(chartContext, event.time, 15 * 60 * 1000)
                      const reaction1h = formatReactionAtOffset(chartContext, event.time, 60 * 60 * 1000)

                      return (
                        <button
                          key={event.id}
                          type="button"
                          onClick={() => setSelectedEventId(event.id)}
                          className={`rounded-xl border p-3 text-left transition-all duration-300 ${selectedEventId === event.id ? 'border-sky-300 bg-sky-50 shadow-sm' : 'border-border bg-background hover:bg-muted/50'} ${recentEventIds.includes(event.id) ? 'ring-2 ring-sky-200' : ''}`}
                          style={recentEventIds.includes(event.id) ? { animation: 'insight-card-in 360ms ease-out' } : undefined}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <div className="line-clamp-2 text-sm font-medium text-foreground">{event.title}</div>
                            </div>
                            <div className="flex shrink-0 items-center gap-1">
                              <div className="text-[11px] text-muted-foreground">
                                {formatDateTime(event.time, { style: 'short' })}
                              </div>
                              {event.sourceUrl && (
                                <a
                                  href={event.sourceUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-muted-foreground transition-colors hover:text-foreground"
                                  onClick={(e) => e.stopPropagation()}
                                  aria-label={t('dashboard.insight.openSource', 'Open source')}
                                >
                                  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden="true">
                                    <path d="M15 3h6v6"></path>
                                    <path d="M10 14 21 3"></path>
                                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                  </svg>
                                </a>
                              )}
                            </div>
                          </div>

                          {event.imageUrl && (
                            <div className="mt-1.5 overflow-hidden rounded-md">
                              <img
                                src={event.imageUrl}
                                alt=""
                                className="h-[72px] w-full object-cover"
                                loading="lazy"
                                onError={(e) => { (e.target as HTMLImageElement).parentElement!.style.display = 'none' }}
                              />
                            </div>
                          )}

                          <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{event.summary}</div>
                          <div className="mt-2 space-y-1.5 text-[10px] text-muted-foreground">
                            <div className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap">
                              {event.evidence.slice(0, 2).map((item, index) => (
                                <span
                                  key={`${event.id}-${index}`}
                                  className="max-w-[140px] truncate rounded-full bg-muted px-1.5 py-0.5"
                                >
                                  {item}
                                </span>
                              ))}
                            </div>
                            <div className="flex items-center gap-1.5 whitespace-nowrap">
                              <ReactionChip label={t('dashboard.insight.after15m', '15m later')} value={reaction15m} compact />
                              <ReactionChip label={t('dashboard.insight.after1h', '1h later')} value={reaction1h} compact />
                            </div>
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex min-h-0 flex-col">
        <Card className="flex h-full min-h-0 flex-col overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between gap-3 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <CardTitle className="text-sm">{t('dashboard.insight.biasTitle', 'Hyper AI Auto Insight')}</CardTitle>
              <InsightRefreshBadge active={showRefreshBadge} />
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <Switch
                checked={aiInsightEnabled}
                onCheckedChange={(checked) => {
                  setAiInsightEnabled(checked)
                  setAiState(checked ? (aiInsight ? 'ready' : 'monitoring') : 'idle')
                  setAiError('')
                  setAiStatusText('')
                  if (!checked) {
                    analysisSeqRef.current += 1
                    activeTaskRef.current = false
                    setCompletedSignature('')
                  }
                }}
              />
              <span>{t('dashboard.insight.aiToggle', 'Hyper AI Auto Insight')}</span>
            </div>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 overflow-y-auto space-y-4">
            {loading ? (
              <InsightEmptyState />
            ) : !aiInsightEnabled && !aiInsight ? (
              <InsightEmptyState />
            ) : showInlineError ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50/70 p-4">
                <div className="text-sm font-medium text-foreground">
                  {t('dashboard.insight.aiFailed', 'Hyper AI analysis failed.')}
                </div>
                <div className="mt-2 text-sm text-muted-foreground whitespace-pre-wrap">
                  {aiError || t('dashboard.insight.aiEmpty', 'Hyper AI returned no readable content.')}
                </div>
              </div>
            ) : aiInsight ? (
              <div className="rounded-2xl border border-border bg-[linear-gradient(180deg,rgba(248,250,252,0.92),rgba(241,245,249,0.74))] p-4">
                <SentimentGauge
                  t={t}
                  sentiment={aiInsight.sentiment}
                  probability={aiInsight.probability}
                  marketEmotion={aiInsight.market_emotion}
                  headline={aiInsight.headline}
                />

                <div className="mt-4 rounded-[1.35rem] border border-border/80 bg-background/85 p-4">
                  <div className="text-sm font-medium leading-7 text-foreground">{aiInsight.summary}</div>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span className={`rounded-full border px-2.5 py-1 ${aiTheme.border} ${aiTheme.softBg} ${aiTheme.softText}`}>
                      {t('dashboard.insight.nextCycleLabel', 'Window')}: {aiInsight.next_cycle_period}
                    </span>
                    {!!aiInsight.similar_pattern && (
                      <span className="rounded-full border border-border/80 bg-muted/45 px-2.5 py-1 text-foreground/80">
                        {t('dashboard.insight.similarPattern', 'Similar pattern')}: {aiInsight.similar_pattern}
                      </span>
                    )}
                  </div>
                  {!!aiInsight.confidence_basis && (
                    <div className="mt-3 rounded-xl border border-border/70 bg-muted/35 px-3 py-2 text-xs italic text-muted-foreground">
                      {t('dashboard.insight.confidenceBasis', 'Confidence basis')}: {aiInsight.confidence_basis}
                    </div>
                  )}
                  {aiGeneratedAt && (
                    <div className="mt-3 text-xs text-muted-foreground">
                      {t('dashboard.insight.aiGeneratedAt', 'Generated at {{time}}', {
                        time: formatDateTime(aiGeneratedAt, { style: 'short' }),
                      })}
                    </div>
                  )}
                </div>

                {aiInsight.sentiment_breakdown && (
                  <div className="mt-4">
                    <BreakdownBars t={t} breakdown={aiInsight.sentiment_breakdown} />
                  </div>
                )}

                {(aiInsight.technical_levels.length > 0 || typeof aiInsight.next_cycle_target_price === 'number' || typeof aiInsight.next_cycle_range_low === 'number' || typeof aiInsight.next_cycle_range_high === 'number') && (
                  <div className="mt-4">
                    <PriceRangeBar t={t} insight={aiInsight} currentPrice={latestChartPrice} />
                  </div>
                )}

                {!!aiInsight.key_drivers.length && (
                  <div className="mt-4 rounded-[1.35rem] border border-border/80 bg-background/85 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                        {t('dashboard.insight.keyDrivers', 'Key Drivers')}
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        {t('dashboard.insight.priorityDrivers', 'Ranked by impact')}
                      </div>
                    </div>
                    <div className="mt-3 space-y-2.5">
                      {aiInsight.key_drivers.map((item, index) => (
                        <DriverCard key={`driver-${index}`} driver={item} />
                      ))}
                    </div>
                  </div>
                )}

                {!!aiInsight.risks.length && (
                  <div className="mt-4 rounded-[1.35rem] border border-border/80 bg-background/85 p-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                      {t('dashboard.insight.risks', 'Risks')}
                    </div>
                    <div className="mt-3 grid gap-2">
                      {aiInsight.risks.map((item, index) => (
                        <div key={`risk-${index}`} className="rounded-xl border border-rose-200/80 bg-rose-50/60 px-3 py-2 text-sm text-rose-900">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!!aiInsight.explanation_markdown && (
                  <div className="mt-4 max-h-64 overflow-y-auto rounded-[1.35rem] border border-border/80 bg-background/85 p-4">
                    <div className="mb-3 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                      {t('dashboard.insight.explanation', 'Explanation')}
                    </div>
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      className="prose prose-sm max-w-none text-foreground dark:prose-invert"
                    >
                      {aiInsight.explanation_markdown}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            ) : (
              <InsightEmptyState />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
