import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'react-hot-toast'
import Cookies from 'js-cookie'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { RefreshCw } from 'lucide-react'
import AiSignalChatModal from './AiSignalChatModal'
import MarketRegimeConfig from './MarketRegimeConfig'
import { useCollectionDays } from '@/lib/useCollectionDays'
import SignalDefinitionDialog from './SignalDefinitionDialog'
import SignalManagerHeader from './SignalManagerHeader'
import { SignalDefinitionsTab, SignalPoolsTab } from './SignalOverviewTabs'
import SignalPoolDialog from './SignalPoolDialog'
import SignalPreviewDialog from './SignalPreviewDialog'
import SignalTriggerLogsTab from './SignalTriggerLogsTab'
import WalletTrackingTab from './WalletTrackingTab'

import {
  createPool,
  createPoolFromConfig,
  createSignal,
  deletePool,
  deleteSignal,
  fetchBatchMarketRegime,
  fetchFactorLibrary,
  fetchMetricAnalysis,
  fetchPoolBacktest,
  fetchSignals,
  fetchTriggerLogs,
  fetchWalletTrackingStatus,
  formatDeps,
  sortByCreatedAtDesc,
  updatePool,
  updateSignal,
  updateWalletTrackingRuntime,
  type FactorItem,
  type MetricAnalysis,
  type PoolSourceType,
  type SignalDefinition,
  type SignalPool,
  type SignalTriggerLog,
  type WalletTrackingRuntimeStatus,
} from './SignalManagerSupport'

export default function SignalManager() {
  const { t } = useTranslation()
  const collectionDays = useCollectionDays()
  const [signals, setSignals] = useState<SignalDefinition[]>([])
  const [pools, setPools] = useState<SignalPool[]>([])
  const [logs, setLogs] = useState<SignalTriggerLog[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('signals')

  // Signal dialog state
  const [signalDialogOpen, setSignalDialogOpen] = useState(false)
  const [editingSignal, setEditingSignal] = useState<SignalDefinition | null>(null)
  const [signalForm, setSignalForm] = useState({
    signal_name: '',
    description: '',
    metric: 'oi_delta',
    operator: 'abs_greater_than',
    threshold: 5,
    time_window: '5m',
    enabled: true,
    exchange: 'hyperliquid',
    // taker_volume composite fields
    direction: 'any',
    ratio_threshold: 1.5,
    volume_threshold: 50000,
    // MACD event fields
    event_types: ['golden_cross', 'death_cross'] as string[],
  })

  // Pool dialog state
  const [poolDialogOpen, setPoolDialogOpen] = useState(false)
  const [editingPool, setEditingPool] = useState<SignalPool | null>(null)
  const [poolForm, setPoolForm] = useState({
    pool_name: '',
    signal_ids: [] as number[],
    symbols: [] as string[],
    enabled: true,
    logic: 'OR' as 'OR' | 'AND',
    exchange: 'hyperliquid',
    source_type: 'market_signals' as PoolSourceType,
    source_config: {
      addresses: [] as string[],
      event_types: ['position_change', 'fill', 'liquidation'] as string[],
      sync_mode: 'ws_only',
    },
  })

  // Metric analysis state
  const [metricAnalysis, setMetricAnalysis] = useState<MetricAnalysis | null>(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)

  // Factor library state
  const [factorLibrary, setFactorLibrary] = useState<FactorItem[]>([])
  const [factorCategory, setFactorCategory] = useState<string>('all')
  const [factorSearch, setFactorSearch] = useState('')

  // Signal preview state
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false)
  const [previewSignal, setPreviewSignal] = useState<SignalDefinition | null>(null)
  const [previewSymbol, setPreviewSymbol] = useState('BTC')
  const [previewData, setPreviewData] = useState<any>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [chartTimeframe, setChartTimeframe] = useState('5m') // Independent chart timeframe

  // Save/delete loading states (for dialog buttons)
  const [savingSignal, setSavingSignal] = useState(false)
  const [savingPool, setSavingPool] = useState(false)

  // AI Signal Chat state
  const [aiChatOpen, setAiChatOpen] = useState(false)
  const [accounts, setAccounts] = useState<any[]>([])
  const [accountsLoading, setAccountsLoading] = useState(false)

  // Watchlist symbols for preview and analysis
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>([])
  const [analysisSymbol, setAnalysisSymbol] = useState('BTC')

  // Pool preview state
  const [previewPool, setPreviewPool] = useState<SignalPool | null>(null)

  // Market Regime state
  const [regimeLoading, setRegimeLoading] = useState(false)

  // Trigger logs filter & pagination state
  const [logsFilterPool, setLogsFilterPool] = useState<number | null>(null)
  const [logsFilterSymbol, setLogsFilterSymbol] = useState<string>('')
  const [logsTotal, setLogsTotal] = useState(0)
  const [logsOffset, setLogsOffset] = useState(0)
  const [walletRuntime, setWalletRuntime] = useState<WalletTrackingRuntimeStatus | null>(null)
  const [walletRuntimeLoading, setWalletRuntimeLoading] = useState(false)
  const LOGS_PAGE_SIZE = 50
  const sortedSignals = sortByCreatedAtDesc(signals)
  const sortedPools = sortByCreatedAtDesc(pools)

  const loadData = async () => {
    try {
      setLoading(true)
      const data = await fetchSignals()
      setSignals(data.signals)
      setPools(data.pools)
      const logsData = await fetchTriggerLogs({ limit: LOGS_PAGE_SIZE, offset: 0 })
      setLogs(logsData.logs)
      setLogsTotal(logsData.total)
      setLogsOffset(0)
    } catch (err) {
      toast.error('Failed to load signal data')
    } finally {
      setLoading(false)
    }
  }

  // Silent refresh - no loading state, for use after save/delete operations
  const refreshDataSilently = async () => {
    try {
      const data = await fetchSignals()
      setSignals(data.signals)
      setPools(data.pools)
    } catch (err) {
      // Silent fail - data will refresh on next load
    }
  }

  const loadAccounts = async () => {
    try {
      setAccountsLoading(true)
      const res = await fetch('/api/account/list')
      if (res.ok) {
        const data = await res.json()
        // API returns array directly, not {accounts: [...]}
        setAccounts(Array.isArray(data) ? data : data.accounts || [])
      }
    } catch (err) {
      console.error('Failed to load accounts:', err)
    } finally {
      setAccountsLoading(false)
    }
  }

  const loadWalletRuntime = async (silent: boolean = false) => {
    try {
      if (!silent) setWalletRuntimeLoading(true)
      const data = await fetchWalletTrackingStatus()
      setWalletRuntime(data)
    } catch (err) {
      if (!silent) toast.error(t('signals.walletTracking.loadStatusFailed', 'Failed to load wallet tracking status'))
    } finally {
      if (!silent) setWalletRuntimeLoading(false)
    }
  }

  // Silent refresh for logs only (no loading state, always fetches first page)
  const refreshLogsSilently = async (poolId: number | null, symbol: string) => {
    try {
      const logsData = await fetchTriggerLogs({
        poolId: poolId ?? undefined,
        symbol: symbol || undefined,
        limit: LOGS_PAGE_SIZE,
        offset: 0,
      })
      setLogs(logsData.logs)
      setLogsTotal(logsData.total)
      setLogsOffset(0)
    } catch {
      // Silent fail - don't interrupt user
    }
  }

  // Load logs with filters (resets to first page)
  const loadLogsWithFilters = async (poolId?: number | null, symbol?: string) => {
    try {
      const logsData = await fetchTriggerLogs({
        poolId: poolId ?? undefined,
        symbol: symbol || undefined,
        limit: LOGS_PAGE_SIZE,
        offset: 0,
      })
      setLogs(logsData.logs)
      setLogsTotal(logsData.total)
      setLogsOffset(0)
    } catch {
      toast.error('Failed to load logs')
    }
  }

  // Load more logs (pagination)
  const loadMoreLogs = async () => {
    try {
      const newOffset = logsOffset + LOGS_PAGE_SIZE
      const logsData = await fetchTriggerLogs({
        poolId: logsFilterPool ?? undefined,
        symbol: logsFilterSymbol || undefined,
        limit: LOGS_PAGE_SIZE,
        offset: newOffset,
      })
      setLogs(prev => [...prev, ...logsData.logs])
      setLogsOffset(newOffset)
    } catch {
      toast.error('Failed to load more logs')
    }
  }

  // Load watchlist symbols
  const loadWatchlist = async (exchange: string = 'hyperliquid') => {
    try {
      const endpoint = exchange === 'binance'
        ? '/api/binance/symbols/watchlist'
        : exchange === 'okx'
          ? '/api/okx/symbols/watchlist'
          : '/api/hyperliquid/symbols/watchlist'
      const res = await fetch(endpoint)
      if (res.ok) {
        const data = await res.json()
        const symbols = data.symbols || []
        setWatchlistSymbols(symbols)
        if (symbols.length > 0 && !symbols.includes(analysisSymbol)) {
          setAnalysisSymbol(symbols[0])
        }
      }
    } catch {
      // Silent fail
    }
  }

  // Check Market Regime for all triggers
  const checkMarketRegime = async () => {
    if (!previewData?.triggers?.length || !previewData?.symbol) return
    setRegimeLoading(true)
    try {
      // Get max timeframe from signal/pool config
      const timeframe = previewData.time_window || '5m'
      const timestamps = previewData.triggers.map((t: any) => t.timestamp)
      const regimeMap = await fetchBatchMarketRegime([previewData.symbol], timeframe, timestamps)
      // Update triggers with regime data
      const updatedTriggers = previewData.triggers.map((t: any) => ({
        ...t,
        market_regime: regimeMap.get(t.timestamp) || null,
      }))
      setPreviewData({ ...previewData, triggers: updatedTriggers })
      toast.success(`Checked regime for ${regimeMap.size} trigger points`)
    } catch (e) {
      toast.error('Failed to check market regime')
    } finally {
      setRegimeLoading(false)
    }
  }

  // Initial load
  useEffect(() => {
    loadData()
    loadAccounts()
    loadWatchlist()
    loadWalletRuntime(true)
    fetchFactorLibrary().then(setFactorLibrary)

    /**
     * URL parameter support: #page-name?view=ID
     * When navigating from Hyper AI created entity card, switch to pools tab
     * and highlight/scroll to the specific pool.
     * Note: Parameters are in the hash (after #), not in search (before #).
     */
    const hash = window.location.hash
    const hashParamIndex = hash.indexOf('?')
    if (hashParamIndex !== -1) {
      const hashParams = new URLSearchParams(hash.slice(hashParamIndex))
      const viewId = hashParams.get('view')
      if (viewId) {
        const numId = Number(viewId)
        if (!isNaN(numId)) {
          // Switch to pools tab to show the created pool
          setActiveTab('pools')
          // TODO: Could scroll to and highlight the specific pool
        }
        // Clean up URL after handling (keep hash without params)
        window.history.replaceState({}, '', window.location.pathname + hash.slice(0, hashParamIndex))
      }
    }
  }, [])

  useEffect(() => {
    if (activeTab !== 'wallets') return
    loadWalletRuntime()
    const interval = setInterval(() => {
      loadWalletRuntime(true)
    }, 15000)
    return () => clearInterval(interval)
  }, [activeTab])

  // Auto-refresh logs only when on logs tab (silent, no loading)
  useEffect(() => {
    if (activeTab !== 'logs') return
    const interval = setInterval(() => {
      refreshLogsSilently(logsFilterPool, logsFilterSymbol)
    }, 15000)
    return () => clearInterval(interval)
  }, [activeTab, logsFilterPool, logsFilterSymbol])

  // Fetch metric analysis when dialog opens or metric/period/symbol/exchange changes
  useEffect(() => {
    if (!signalDialogOpen) {
      setMetricAnalysis(null)
      return
    }
    // Clear previous analysis immediately to avoid data mismatch during loading
    setMetricAnalysis(null)
    const loadAnalysis = async () => {
      // Skip analysis for event-based metrics (no threshold suggestions needed)
      if (signalForm.metric === 'macd' || signalForm.metric === 'taker_volume' || signalForm.metric === '_pick_factor') {
        setAnalysisLoading(false)
        return
      }
      setAnalysisLoading(true)
      try {
        // Factor metrics use evaluate API for effectiveness data
        if (signalForm.metric.startsWith('factor:')) {
          const factorName = signalForm.metric.split(':')[1]
          const factor = factorLibrary.find(f => f.name === factorName)
          if (!factor) { setMetricAnalysis(null); return }
          const res = await fetch('/api/factors/evaluate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              expression: factor.expression,
              symbol: analysisSymbol,
              exchange: signalForm.exchange,
              period: signalForm.time_window,
            }),
          })
          if (!res.ok) { setMetricAnalysis(null); return }
          const evalData = await res.json()
          if (evalData.status === 'ok') {
            setMetricAnalysis({
              status: 'ok',
              metric: signalForm.metric,
              sample_count: 300,
              time_range_hours: 300,
              statistics: null as any,
              suggestions: null as any,
              factor_effectiveness: evalData.effectiveness,
              factor_latest_value: evalData.latest_value,
              factor_percentiles: evalData.percentiles,
            } as any)
          } else {
            setMetricAnalysis(null)
          }
        } else {
          const data = await fetchMetricAnalysis(analysisSymbol, signalForm.metric, signalForm.time_window, signalForm.exchange)
          setMetricAnalysis(data)
        }
      } catch {
        setMetricAnalysis(null)
      } finally {
        setAnalysisLoading(false)
      }
    }
    loadAnalysis()
  }, [signalDialogOpen, signalForm.metric, signalForm.time_window, signalForm.exchange, analysisSymbol])

  const openSignalDialog = (signal?: SignalDefinition) => {
    if (signal) {
      setEditingSignal(signal)
      const cond = signal.trigger_condition
      // Map old metric names to new names (backward compatibility)
      const metricNameMap: Record<string, string> = {
        'oi_delta_percent': 'oi_delta',
        'funding_rate': 'funding',
        'taker_buy_ratio': 'taker_ratio',
      }
      const normalizedMetric = metricNameMap[cond.metric] || cond.metric || 'oi_delta'
      setSignalForm({
        signal_name: signal.signal_name,
        description: signal.description || '',
        metric: normalizedMetric,
        operator: cond.operator || 'abs_greater_than',
        threshold: cond.threshold ?? 5,
        time_window: cond.time_window || '5m',
        enabled: signal.enabled,
        exchange: signal.exchange || 'hyperliquid',
        // taker_volume composite fields
        direction: (cond as any).direction || 'any',
        ratio_threshold: (cond as any).ratio_threshold ?? 1.5,
        volume_threshold: (cond as any).volume_threshold ?? 50000,
        // MACD event fields
        event_types: (cond as any).event_types || ['golden_cross', 'death_cross'],
      })
    } else {
      setEditingSignal(null)
      setSignalForm({
        signal_name: '',
        description: '',
        metric: 'oi_delta',
        operator: 'abs_greater_than',
        threshold: 5,
        time_window: '5m',
        enabled: true,
        exchange: 'hyperliquid',
        direction: 'any',
        ratio_threshold: 1.5,
        volume_threshold: 50000,
        event_types: ['golden_cross', 'death_cross'],
      })
    }
    setSignalDialogOpen(true)
  }

  const handleSaveSignal = async () => {
    setSavingSignal(true)
    try {
      // Build trigger_condition based on metric type
      let trigger_condition: Record<string, unknown>
      if (signalForm.metric === 'taker_volume') {
        // Composite signal: direction + ratio + volume
        trigger_condition = {
          metric: signalForm.metric,
          direction: signalForm.direction,
          ratio_threshold: signalForm.ratio_threshold,
          volume_threshold: signalForm.volume_threshold,
          time_window: signalForm.time_window,
        }
      } else if (signalForm.metric === 'macd') {
        // MACD event-based signal
        if (signalForm.event_types.length === 0) {
          toast.error('Please select at least one MACD event type')
          setSavingSignal(false)
          return
        }
        trigger_condition = {
          metric: signalForm.metric,
          event_types: signalForm.event_types,
          time_window: signalForm.time_window,
        }
      } else {
        // Standard signal: operator + threshold
        trigger_condition = {
          metric: signalForm.metric,
          operator: signalForm.operator,
          threshold: signalForm.threshold,
          time_window: signalForm.time_window,
        }
      }
      const data = {
        signal_name: signalForm.signal_name,
        description: signalForm.description,
        trigger_condition,
        enabled: signalForm.enabled,
        exchange: signalForm.exchange,
      }
      if (editingSignal) {
        await updateSignal(editingSignal.id, data)
        toast.success('Signal updated')
      } else {
        await createSignal(data)
        toast.success('Signal created')
      }
      setSignalDialogOpen(false)
      refreshDataSilently()
    } catch (err) {
      toast.error('Failed to save signal')
    } finally {
      setSavingSignal(false)
    }
  }

  const handleDeleteSignal = async (id: number) => {
    if (!confirm('Delete this signal?')) return
    try {
      const data = await deleteSignal(id)
      if (data.deleted) {
        toast.success('Signal deleted')
        refreshDataSilently()
      } else if (data.dependencies) {
        const msg = formatDeps(data.dependencies as string[], t)
        toast.error(`${t('common.cannotDelete')}: ${msg}`, { duration: 5000 })
      } else {
        toast.error((data.error as string) || 'Failed to delete signal')
      }
    } catch (err) {
      toast.error('Failed to delete signal')
    }
  }

  const openPreviewDialog = async (signal: SignalDefinition, symbol: string = 'BTC') => {
    // Get time_window from signal's trigger condition and set as default chart timeframe
    const signalTimeWindow = signal.trigger_condition?.time_window || '5m'
    const signalExchange = signal.exchange || 'hyperliquid'
    setChartTimeframe(signalTimeWindow)
    setPreviewSignal(signal)
    setPreviewPool(null)
    setPreviewSymbol(symbol)
    setPreviewDialogOpen(true)
    setPreviewLoading(true)
    setPreviewData(null)

    // Load watchlist for the signal's exchange
    loadWatchlist(signalExchange)

    try {
      // Step 1: Fetch K-lines from market API (ensures fresh data)
      // Use 500 klines to match the K-line page and provide more historical context
      // Include MACD indicator for chart display
      const klineRes = await fetch(
        `/api/market/kline-with-indicators/${symbol}?market=${signalExchange}&period=${signalTimeWindow}&count=500&indicators=MACD`
      )
      if (!klineRes.ok) throw new Error('Failed to fetch K-line data')
      const klineData = await klineRes.json()

      if (!klineData.klines || klineData.klines.length === 0) {
        throw new Error('No K-line data available')
      }

      // Get time range from K-lines (timestamps are in seconds from market API)
      const klines = klineData.klines
      const klineMinTs = Math.min(...klines.map((k: any) => k.timestamp)) * 1000
      const klineMaxTs = Math.max(...klines.map((k: any) => k.timestamp)) * 1000

      // Step 2: Fetch triggers from backtest API with time range
      const triggerRes = await fetch(
        `/api/signals/backtest/${signal.id}?symbol=${symbol}&kline_min_ts=${klineMinTs}&kline_max_ts=${klineMaxTs}`
      )
      if (!triggerRes.ok) throw new Error('Failed to fetch trigger data')
      const triggerData = await triggerRes.json()

      // Combine data for preview chart
      // Convert K-line timestamps to milliseconds for consistency
      const formattedKlines = klines.map((k: any) => ({
        timestamp: k.timestamp * 1000,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      }))

      setPreviewData({
        ...triggerData,
        klines: formattedKlines,
        kline_count: formattedKlines.length,
        macd: klineData.indicators?.MACD,
      })
    } catch (err) {
      toast.error('Failed to load preview data')
    } finally {
      setPreviewLoading(false)
    }
  }

  const openPoolPreviewDialog = async (pool: SignalPool, symbol: string = 'BTC') => {
    // Use first signal's time_window or default to 5m, set as default chart timeframe
    const firstSignalId = pool.signal_ids[0]
    const firstSignal = signals.find(s => s.id === firstSignalId)
    const poolTimeWindow = firstSignal?.trigger_condition?.time_window || '5m'
    const poolExchange = pool.exchange || 'hyperliquid'
    setChartTimeframe(poolTimeWindow)
    setPreviewPool(pool)
    setPreviewSignal(null)
    setPreviewSymbol(symbol)
    setPreviewDialogOpen(true)
    setPreviewLoading(true)
    setPreviewData(null)

    // Load watchlist for the pool's exchange
    loadWatchlist(poolExchange)

    try {
      // Step 1: Fetch K-lines with MACD indicator
      const klineRes = await fetch(
        `/api/market/kline-with-indicators/${symbol}?market=${poolExchange}&period=${poolTimeWindow}&count=500&indicators=MACD`
      )
      if (!klineRes.ok) throw new Error('Failed to fetch K-line data')
      const klineData = await klineRes.json()

      if (!klineData.klines || klineData.klines.length === 0) {
        throw new Error('No K-line data available')
      }

      const klines = klineData.klines
      const klineMinTs = Math.min(...klines.map((k: any) => k.timestamp)) * 1000
      const klineMaxTs = Math.max(...klines.map((k: any) => k.timestamp)) * 1000

      // Step 2: Fetch pool backtest
      const triggerRes = await fetch(
        `/api/signals/pool-backtest/${pool.id}?symbol=${symbol}&kline_min_ts=${klineMinTs}&kline_max_ts=${klineMaxTs}`
      )
      if (!triggerRes.ok) throw new Error('Failed to fetch pool backtest')
      const triggerData = await triggerRes.json()

      const formattedKlines = klines.map((k: any) => ({
        timestamp: k.timestamp * 1000,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      }))

      setPreviewData({
        ...triggerData,
        klines: formattedKlines,
        kline_count: formattedKlines.length,
        isPoolPreview: true,
        macd: klineData.indicators?.MACD,
      })
    } catch (err) {
      toast.error('Failed to load pool preview data')
    } finally {
      setPreviewLoading(false)
    }
  }

  // AI Signal handlers - returns true on success for UI feedback
  const handleAiCreateSignal = async (config: any): Promise<boolean> => {
    try {
      const signalData = {
        signal_name: config.name,
        description: config.description || '',
        trigger_condition: config.trigger_condition,
        enabled: true,
        exchange: config.exchange || 'hyperliquid',
      }
      await createSignal(signalData)
      toast.success(`Signal "${config.name}" created`)
      // Silent refresh - don't close dialog, user may want to create more signals
      const data = await fetchSignals()
      setSignals(data.signals)
      setPools(data.pools)
      return true
    } catch (err) {
      toast.error('Failed to create signal')
      return false
    }
  }

  // AI Signal Pool handler - creates pool from AI-generated config
  const handleAiCreatePool = async (config: any): Promise<boolean> => {
    try {
      const poolConfig = {
        name: config.name,
        symbol: config.symbol,
        description: config.description || '',
        logic: config.logic || 'AND',
        signals: config.signals || [],
        exchange: config.exchange || 'hyperliquid',
      }
      const result = await createPoolFromConfig(poolConfig)
      toast.success(`Signal Pool "${config.name}" created with ${result.signals.length} signals`)
      // Refresh signals and pools
      const data = await fetchSignals()
      setSignals(data.signals)
      setPools(data.pools)
      return true
    } catch (err: any) {
      toast.error(err.message || 'Failed to create signal pool')
      return false
    }
  }

  const handleAiPreviewSignal = async (config: any) => {
    // Create a temporary signal object for preview
    const tempSignal: SignalDefinition = {
      id: 0,
      signal_name: config.name,
      description: config.description || '',
      trigger_condition: config.trigger_condition,
      enabled: true,
      exchange: config.exchange || 'hyperliquid',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    const symbol = config.symbol || 'BTC'
    const tempTimeWindow = config.trigger_condition?.time_window || '5m'
    const tempExchange = config.exchange || 'hyperliquid'
    setChartTimeframe(tempTimeWindow)
    setPreviewSignal(tempSignal)
    setPreviewSymbol(symbol)
    setPreviewDialogOpen(true)
    setPreviewLoading(true)
    setPreviewData(null)

    try {
      // Fetch K-lines with MACD indicator
      const klineRes = await fetch(
        `/api/market/kline-with-indicators/${symbol}?market=${tempExchange}&period=${tempTimeWindow}&count=500&indicators=MACD`
      )
      if (!klineRes.ok) throw new Error('Failed to fetch K-line data')
      const klineData = await klineRes.json()

      if (!klineData.klines || klineData.klines.length === 0) {
        throw new Error('No K-line data available')
      }

      const klines = klineData.klines
      const klineMinTs = Math.min(...klines.map((k: any) => k.timestamp)) * 1000
      const klineMaxTs = Math.max(...klines.map((k: any) => k.timestamp)) * 1000

      // Use temp backtest API for preview
      const triggerRes = await fetch('/api/signals/backtest-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          triggerCondition: config.trigger_condition,
          klineMinTs,
          klineMaxTs,
          exchange: tempExchange,
        }),
      })
      if (!triggerRes.ok) throw new Error('Failed to fetch trigger data')
      const triggerData = await triggerRes.json()

      const formattedKlines = klines.map((k: any) => ({
        timestamp: k.timestamp * 1000,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      }))

      setPreviewData({
        ...triggerData,
        klines: formattedKlines,
        kline_count: formattedKlines.length,
        macd: klineData.indicators?.MACD,
      })
    } catch (err) {
      toast.error('Failed to load preview data')
    } finally {
      setPreviewLoading(false)
    }
  }

  // Refresh preview with new chart timeframe (keeps same signal/pool, just changes K-line period)
  const refreshPreviewWithTimeframe = async (newTimeframe: string) => {
    setChartTimeframe(newTimeframe)
    setPreviewLoading(true)

    // Get exchange from current preview context
    const previewExchange = previewPool?.exchange || previewSignal?.exchange || 'hyperliquid'

    try {
      // Fetch K-lines with new timeframe and MACD indicator
      const klineRes = await fetch(
        `/api/market/kline-with-indicators/${previewSymbol}?market=${previewExchange}&period=${newTimeframe}&count=500&indicators=MACD`
      )
      if (!klineRes.ok) throw new Error('Failed to fetch K-line data')
      const klineData = await klineRes.json()

      if (!klineData.klines || klineData.klines.length === 0) {
        throw new Error('No K-line data available')
      }

      const klines = klineData.klines
      const klineMinTs = Math.min(...klines.map((k: any) => k.timestamp)) * 1000
      const klineMaxTs = Math.max(...klines.map((k: any) => k.timestamp)) * 1000

      // Fetch triggers based on whether it's a pool or signal preview
      let triggerData
      if (previewPool) {
        const triggerRes = await fetch(
          `/api/signals/pool-backtest/${previewPool.id}?symbol=${previewSymbol}&kline_min_ts=${klineMinTs}&kline_max_ts=${klineMaxTs}`
        )
        if (!triggerRes.ok) throw new Error('Failed to fetch pool backtest')
        triggerData = await triggerRes.json()
      } else if (previewSignal) {
        if (previewSignal.id === 0) {
          // Temp signal (AI preview)
          const triggerRes = await fetch('/api/signals/backtest-preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              symbol: previewSymbol,
              triggerCondition: previewSignal.trigger_condition,
              klineMinTs,
              klineMaxTs,
              exchange: previewExchange,
            }),
          })
          if (!triggerRes.ok) throw new Error('Failed to fetch trigger data')
          triggerData = await triggerRes.json()
        } else {
          // Saved signal (backtest_signal gets exchange from DB)
          const triggerRes = await fetch(
            `/api/signals/backtest/${previewSignal.id}?symbol=${previewSymbol}&kline_min_ts=${klineMinTs}&kline_max_ts=${klineMaxTs}`
          )
          if (!triggerRes.ok) throw new Error('Failed to fetch trigger data')
          triggerData = await triggerRes.json()
        }
      }

      const formattedKlines = klines.map((k: any) => ({
        timestamp: k.timestamp * 1000,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      }))

      setPreviewData({
        ...triggerData,
        klines: formattedKlines,
        kline_count: formattedKlines.length,
        isPoolPreview: !!previewPool,
        chart_timeframe: newTimeframe,
        macd: klineData.indicators?.MACD,
      })
    } catch (err) {
      toast.error('Failed to refresh preview')
    } finally {
      setPreviewLoading(false)
    }
  }

  const openPoolDialog = (pool?: SignalPool, initialSourceType: PoolSourceType = 'market_signals') => {
    if (pool) {
      setEditingPool(pool)
      setPoolForm({
        pool_name: pool.pool_name,
        signal_ids: pool.signal_ids,
        symbols: pool.symbols,
        enabled: pool.enabled,
        logic: pool.logic || 'OR',
        exchange: pool.exchange || 'hyperliquid',
        source_type: pool.source_type || 'market_signals',
        source_config: {
          addresses: pool.source_config?.addresses || [],
          event_types: pool.source_config?.event_types || ['position_change', 'fill', 'liquidation'],
          sync_mode: pool.source_config?.sync_mode || 'ws_only',
        },
      })
    } else {
      setEditingPool(null)
      setPoolForm({
        pool_name: '',
        signal_ids: [],
        symbols: [],
        enabled: true,
        logic: 'OR',
        exchange: 'hyperliquid',
        source_type: initialSourceType,
        source_config: {
          addresses: [],
          event_types: ['position_change', 'fill', 'liquidation'],
          sync_mode: 'ws_only',
        },
      })
    }
    setPoolDialogOpen(true)
  }

  const handleSavePool = async () => {
    setSavingPool(true)
    try {
      if (poolForm.source_type === 'wallet_tracking') {
        if (!(poolForm.source_config.addresses || []).length) {
          toast.error(t('signals.walletTracking.addressRequired', 'Select at least one synced wallet'))
          return
        }
        if (!(poolForm.source_config.event_types || []).length) {
          toast.error(t('signals.walletTracking.eventTypeRequired', 'Select at least one wallet event type'))
          return
        }
      }
      const data = {
        pool_name: poolForm.pool_name,
        signal_ids: poolForm.signal_ids,
        symbols: poolForm.symbols,
        enabled: poolForm.enabled,
        logic: poolForm.logic,
        exchange: poolForm.exchange,
        source_type: poolForm.source_type,
        source_config: poolForm.source_config,
      }
      if (editingPool) {
        await updatePool(editingPool.id, data)
        toast.success('Pool updated')
      } else {
        await createPool(data)
        toast.success('Pool created')
      }
      setPoolDialogOpen(false)
      refreshDataSilently()
    } catch (err) {
      toast.error('Failed to save pool')
    } finally {
      setSavingPool(false)
    }
  }

  const handleDeletePool = async (id: number) => {
    if (!confirm('Delete this pool?')) return
    try {
      const data = await deletePool(id)
      if (data.deleted) {
        toast.success('Pool deleted')
        refreshDataSilently()
      } else if (data.dependencies) {
        const msg = formatDeps(data.dependencies as string[], t)
        toast.error(`${t('common.cannotDelete')}: ${msg}`, { duration: 5000 })
      } else {
        toast.error((data.error as string) || 'Failed to delete pool')
      }
    } catch (err) {
      toast.error('Failed to delete pool')
    }
  }

  const toggleSymbol = (symbol: string) => {
    setPoolForm(prev => ({
      ...prev,
      symbols: prev.symbols.includes(symbol)
        ? prev.symbols.filter(s => s !== symbol)
        : [...prev.symbols, symbol]
    }))
  }

  const toggleSignalInPool = (signalId: number) => {
    setPoolForm(prev => ({
      ...prev,
      signal_ids: prev.signal_ids.includes(signalId)
        ? prev.signal_ids.filter(id => id !== signalId)
        : [...prev.signal_ids, signalId]
    }))
  }

  const toggleWalletEventType = (eventType: string) => {
    setPoolForm(prev => {
      const current = prev.source_config.event_types || []
      const nextEventTypes = current.includes(eventType)
        ? current.filter(item => item !== eventType)
        : [...current, eventType]
      return {
        ...prev,
        source_config: {
          ...prev.source_config,
          event_types: nextEventTypes,
        },
      }
    })
  }

  const toggleWalletAddressInPool = (address: string) => {
    setPoolForm(prev => {
      const current = prev.source_config.addresses || []
      const nextAddresses = current.includes(address)
        ? current.filter(item => item !== address)
        : [...current, address]
      return {
        ...prev,
        source_config: {
          ...prev.source_config,
          addresses: nextAddresses,
        },
      }
    })
  }

  const handleEnableWalletTracking = async () => {
    try {
      setWalletRuntimeLoading(true)
      const accessToken = Cookies.get('arena_token')
      const data = await updateWalletTrackingRuntime({
        enabled: true,
        access_token: accessToken,
      })
      setWalletRuntime(data)
      toast.success(t('signals.walletTracking.enabledSuccess', 'Wallet tracking integration enabled'))
    } catch (err) {
      toast.error(t('signals.walletTracking.enableFailed', 'Failed to enable wallet tracking integration'))
    } finally {
      setWalletRuntimeLoading(false)
    }
  }

  const handleDisableWalletTracking = async () => {
    try {
      setWalletRuntimeLoading(true)
      const data = await updateWalletTrackingRuntime({ enabled: false })
      setWalletRuntime(data)
      toast.success(t('signals.walletTracking.disabledSuccess', 'Wallet tracking integration disabled'))
    } catch (err) {
      toast.error(t('signals.walletTracking.disableFailed', 'Failed to disable wallet tracking integration'))
    } finally {
      setWalletRuntimeLoading(false)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-64">{t('signals.loading', 'Loading...')}</div>
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 p-4 space-y-4">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <SignalManagerHeader
          t={t}
          collectionDays={collectionDays}
          onNewSignal={() => openSignalDialog()}
          onNewPool={() => openPoolDialog()}
          onOpenAiChat={() => setAiChatOpen(true)}
        />

        <TabsContent value="signals" className="space-y-4 flex-1 min-h-0 overflow-y-auto">
          <SignalDefinitionsTab
            signals={sortedSignals}
            t={t}
            onEdit={openSignalDialog}
            onDelete={handleDeleteSignal}
            onBacktest={openPreviewDialog}
          />
        </TabsContent>

        <TabsContent value="pools" className="space-y-4 flex-1 min-h-0 overflow-y-auto">
          <SignalPoolsTab
            pools={sortedPools}
            signals={signals}
            watchlistSymbols={watchlistSymbols}
            t={t}
            onEdit={openPoolDialog}
            onDelete={handleDeletePool}
            onBacktest={openPoolPreviewDialog}
          />
        </TabsContent>

        <TabsContent value="wallets" className="space-y-4 flex-1 min-h-0 overflow-y-auto">
          <WalletTrackingTab
            t={t}
            walletRuntime={walletRuntime}
            walletRuntimeLoading={walletRuntimeLoading}
            onEnable={handleEnableWalletTracking}
            onDisable={handleDisableWalletTracking}
            onCreateWalletPool={() => openPoolDialog(undefined, 'wallet_tracking')}
          />
        </TabsContent>

        <TabsContent value="logs" className="flex-1">
          <SignalTriggerLogsTab
            t={t}
            logs={logs}
            logsTotal={logsTotal}
            pools={pools}
            signals={signals}
            watchlistSymbols={watchlistSymbols}
            logsFilterPool={logsFilterPool}
            logsFilterSymbol={logsFilterSymbol}
            onPoolChange={setLogsFilterPool}
            onSymbolChange={setLogsFilterSymbol}
            loadLogsWithFilters={loadLogsWithFilters}
            onLoadMore={loadMoreLogs}
          />
        </TabsContent>

        <TabsContent value="regime" className="space-y-4">
          <MarketRegimeConfig />
        </TabsContent>
      </Tabs>

      <SignalDefinitionDialog
        open={signalDialogOpen}
        editingSignal={editingSignal}
        signalForm={signalForm}
        setSignalForm={setSignalForm}
        factorLibrary={factorLibrary}
        factorCategory={factorCategory}
        factorSearch={factorSearch}
        metricAnalysis={metricAnalysis}
        analysisLoading={analysisLoading}
        analysisSymbol={analysisSymbol}
        watchlistSymbols={watchlistSymbols}
        savingSignal={savingSignal}
        t={t}
        onOpenChange={(open) => {
          setSignalDialogOpen(open)
          if (!open) {
            setFactorSearch('')
            setFactorCategory('all')
          }
        }}
        onSave={handleSaveSignal}
        setFactorCategory={setFactorCategory}
        setFactorSearch={setFactorSearch}
        setAnalysisSymbol={setAnalysisSymbol}
      />

      <SignalPoolDialog
        open={poolDialogOpen}
        onOpenChange={setPoolDialogOpen}
        editingPool={editingPool}
        poolForm={poolForm}
        setPoolForm={setPoolForm}
        signals={signals}
        watchlistSymbols={watchlistSymbols}
        walletRuntime={walletRuntime}
        savingPool={savingPool}
        t={t}
        onSave={handleSavePool}
        loadWatchlist={loadWatchlist}
        toggleSignalInPool={toggleSignalInPool}
        toggleSymbol={toggleSymbol}
        toggleWalletAddressInPool={toggleWalletAddressInPool}
        toggleWalletEventType={toggleWalletEventType}
      />

      <SignalPreviewDialog
        open={previewDialogOpen}
        onOpenChange={setPreviewDialogOpen}
        previewPool={previewPool}
        previewSignal={previewSignal}
        previewLoading={previewLoading}
        previewData={previewData}
        regimeLoading={regimeLoading}
        chartTimeframe={chartTimeframe}
        watchlistSymbols={watchlistSymbols}
        previewSymbol={previewSymbol}
        t={t}
        onCheckMarketRegime={checkMarketRegime}
        onRefreshWithTimeframe={refreshPreviewWithTimeframe}
        onOpenPoolPreview={openPoolPreviewDialog}
        onOpenSignalPreview={openPreviewDialog}
      />

      {/* AI Signal Chat Modal */}
      <AiSignalChatModal
        open={aiChatOpen}
        onOpenChange={setAiChatOpen}
        onCreateSignal={handleAiCreateSignal}
        onCreatePool={handleAiCreatePool}
        onPreviewSignal={handleAiPreviewSignal}
        accounts={accounts}
        accountsLoading={accountsLoading}
      />
    </div>
  )
}
