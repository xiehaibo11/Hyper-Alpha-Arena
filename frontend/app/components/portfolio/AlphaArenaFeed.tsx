import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  ArenaAccountMeta,
  ArenaModelChatEntry,
  ArenaPositionsAccount,
  ArenaTrade,
  checkPnlSyncStatus,
  getArenaModelChat,
  getArenaPositions,
  getArenaTrades,
  getAccounts,
  getModelChatSnapshots,
  ModelChatSnapshots,
  getHyperliquidWatchlist,
  updateArenaPnl,
  ProgramExecutionLog,
  getProgramExecutions,
} from '@/lib/api'
import { useArenaData } from '@/contexts/ArenaDataContext'
import { useTradingMode } from '@/contexts/TradingModeContext'
import { Button } from '@/components/ui/button'
import { getModelLogo } from './logoAssets'
import FlipNumber from './FlipNumber'
import HighlightWrapper from './HighlightWrapper'
import { formatDateTime } from '@/lib/dateTime'
import { Loader2, Settings, RefreshCw } from 'lucide-react'
import { copyToClipboard } from '@/lib/utils'
import { TradingAccount, updateDashboardVisibility } from '@/lib/api'
import AlphaArenaFeedFilterBar from './AlphaArenaFeedFilterBar'
import AlphaArenaPnlControls from './AlphaArenaPnlControls'
import AlphaArenaPositionsTab from './AlphaArenaPositionsTab'
import AlphaArenaProgramTab from './AlphaArenaProgramTab'
import AlphaArenaTradeCard from './AlphaArenaTradeCard'
import DashboardVisibilityDialog from './DashboardVisibilityDialog'
import {
  DEFAULT_LIMIT,
  MODEL_CHAT_LIMIT,
  PROGRAM_LOG_LIMIT,
  type AlphaArenaFeedProps,
  type CacheKey,
  type FeedTab,
} from './AlphaArenaFeedTypes'

// Use formatDateTime from @/lib/dateTime with 'short' style for compact display
const formatDate = (value?: string | null) => formatDateTime(value, { style: 'short' })

export default function AlphaArenaFeed({
  refreshKey,
  autoRefreshInterval = 60_000,
  wsRef,
  selectedAccount: selectedAccountProp,
  onSelectedAccountChange,
  walletAddress,
  onPageChange,
  onSelectedSymbolChange,
  onSelectedExchangeChange,
  onArenaActivity,
}: AlphaArenaFeedProps) {
  const { t } = useTranslation()
  const { getData, updateData } = useArenaData()
  const { tradingMode } = useTradingMode()
  const [activeTab, setActiveTab] = useState<FeedTab>('trades')
  const [allTraderOptions, setAllTraderOptions] = useState<ArenaAccountMeta[]>([])
  const [loadingAccounts, setLoadingAccounts] = useState(false)
  const [internalSelectedAccount, setInternalSelectedAccount] = useState<number | 'all'>(
    selectedAccountProp ?? 'all',
  )
  const [expandedChat, setExpandedChat] = useState<number | null>(null)
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({})
  const [copiedSections, setCopiedSections] = useState<Record<string, boolean>>({})
  const [manualRefreshKey, setManualRefreshKey] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [loadingTrades, setLoadingTrades] = useState(false)
  const [loadingModelChat, setLoadingModelChat] = useState(false)
  const [loadingPositions, setLoadingPositions] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [updatingPnl, setUpdatingPnl] = useState(false)
  const [pnlUpdateResult, setPnlUpdateResult] = useState<string | null>(null)
  const [showPnlConfirm, setShowPnlConfirm] = useState(false)
  const [needsSync, setNeedsSync] = useState(false)
  const [unsyncCount, setUnsyncCount] = useState(0)

  const [trades, setTrades] = useState<ArenaTrade[]>([])
  const [modelChat, setModelChat] = useState<ArenaModelChatEntry[]>([])
  const [positions, setPositions] = useState<ArenaPositionsAccount[]>([])
  const [accountsMeta, setAccountsMeta] = useState<ArenaAccountMeta[]>([])

  // Program execution logs state
  const [programLogs, setProgramLogs] = useState<ProgramExecutionLog[]>([])
  const [loadingProgram, setLoadingProgram] = useState(false)
  const [expandedProgramLog, setExpandedProgramLog] = useState<number | null>(null)
  const [copiedProgramLog, setCopiedProgramLog] = useState<number | null>(null)
  const [copiedProgramSection, setCopiedProgramSection] = useState<string | null>(null)

  // Lazy loading states for ModelChat
  const [hasMoreModelChat, setHasMoreModelChat] = useState(true)
  const [isLoadingMoreModelChat, setIsLoadingMoreModelChat] = useState(false)

  // Lazy loading states for Program
  const [hasMoreProgram, setHasMoreProgram] = useState(true)
  const [isLoadingMoreProgram, setIsLoadingMoreProgram] = useState(false)

  // Snapshot lazy loading cache and states
  const snapshotCache = useRef<Map<number, ModelChatSnapshots>>(new Map())
  const [loadingSnapshots, setLoadingSnapshots] = useState<Set<number>>(new Set())

  // New states for symbol selection
  const [symbolOptions, setSymbolOptions] = useState<string[]>([])
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)

  // Exchange filter state
  const [selectedExchange, setSelectedExchange] = useState<'all' | 'hyperliquid' | 'binance'>('all')

  // Feed-level filter states (shared by ModelChat and Program tabs)
  const [feedTimeRange, setFeedTimeRange] = useState<'all' | '3d' | '7d' | 'custom'>('all')
  const [feedAction, setFeedAction] = useState<string>('') // '' = all, 'buy'/'sell'/'hold'/'close'
  const [feedCustomFrom, setFeedCustomFrom] = useState<string>('') // local datetime string
  const [feedCustomTo, setFeedCustomTo] = useState<string>('') // local datetime string
  const [showCustomDatePicker, setShowCustomDatePicker] = useState(false)

  // Derived: whether any feed filter is active (used to pause auto-refresh)
  const isFeedFiltered = feedTimeRange !== 'all' || feedAction !== ''

  // Compute UTC ISO strings from feed filter for API calls
  const feedAfterTimeUTC = useMemo(() => {
    if (feedTimeRange === '3d') {
      const d = new Date()
      d.setDate(d.getDate() - 3)
      return d.toISOString()
    }
    if (feedTimeRange === '7d') {
      const d = new Date()
      d.setDate(d.getDate() - 7)
      return d.toISOString()
    }
    if (feedTimeRange === 'custom' && feedCustomFrom) {
      return new Date(feedCustomFrom).toISOString()
    }
    return undefined
  }, [feedTimeRange, feedCustomFrom])

  const feedBeforeTimeUTC = useMemo(() => {
    if (feedTimeRange === 'custom' && feedCustomTo) {
      return new Date(feedCustomTo).toISOString()
    }
    return undefined
  }, [feedTimeRange, feedCustomTo])

  // Dashboard visibility config dialog
  const [showVisibilityConfig, setShowVisibilityConfig] = useState(false)
  const [visibilityAccounts, setVisibilityAccounts] = useState<TradingAccount[]>([])
  const [visibilityChanges, setVisibilityChanges] = useState<Map<number, boolean>>(new Map())
  const [savingVisibility, setSavingVisibility] = useState(false)
  const [loadingVisibilityAccounts, setLoadingVisibilityAccounts] = useState(false)

  // Track seen items for highlight animation
  const seenTradeIds = useRef<Set<number>>(new Set())
  const seenDecisionIds = useRef<Set<number>>(new Set())
  const prevManualRefreshKey = useRef(manualRefreshKey)
  const prevRefreshKey = useRef(refreshKey)
  const prevTradingMode = useRef(tradingMode)
  const latestModelChatIdRef = useRef<number | null>(null)
  const latestProgramLogIdRef = useRef<number | null>(null)

  const emitArenaActivity = useCallback((activity: {
    accountId: number
    exchange?: string | null
    state: 'program_running' | 'ai_thinking'
  }) => {
    if (!onArenaActivity) return
    onArenaActivity({
      accountId: activity.accountId,
      exchange: activity.exchange || 'hyperliquid',
      state: activity.state,
    })
  }, [onArenaActivity])

  // Sync external account selection with internal state
  useEffect(() => {
    if (selectedAccountProp !== undefined) {
      setInternalSelectedAccount(selectedAccountProp)
    }
  }, [selectedAccountProp])

  // Compute active account and cache key
  const activeAccount = useMemo(() => selectedAccountProp ?? internalSelectedAccount, [selectedAccountProp, internalSelectedAccount])
  const prevActiveAccount = useRef<number | 'all'>(activeAccount)
  const cacheKey: CacheKey = useMemo(() => {
    const accountKey = activeAccount === 'all' ? 'all' : String(activeAccount)
    const walletKey = walletAddress ? walletAddress.toLowerCase() : 'nowallet'
    return `${accountKey}_${tradingMode}_${walletKey}`
  }, [activeAccount, tradingMode, walletAddress])

  // Filter data by selected exchange (frontend filtering)
  const filteredTrades = useMemo(() => {
    if (selectedExchange === 'all') return trades
    return trades.filter(t => (t.exchange || 'hyperliquid') === selectedExchange)
  }, [trades, selectedExchange])

  const filteredModelChat = useMemo(() => {
    if (selectedExchange === 'all') return modelChat
    return modelChat.filter(m => (m.exchange || 'hyperliquid') === selectedExchange)
  }, [modelChat, selectedExchange])

  const filteredProgramLogs = useMemo(() => {
    if (selectedExchange === 'all') return programLogs
    return programLogs.filter(p => (p.exchange || 'hyperliquid') === selectedExchange)
  }, [programLogs, selectedExchange])

  // Initialize from global state on mount or account change
  useEffect(() => {
    const globalData = getData(cacheKey)
    if (globalData) {
      setTrades(globalData.trades)
      setModelChat(globalData.modelChat)
      setPositions(globalData.positions)
      setAccountsMeta(globalData.accountsMeta)
      setLoadingTrades(false)
      setLoadingModelChat(false)
      setLoadingPositions(false)
    }
  }, [cacheKey, getData])

  const writeCache = useCallback(
    (key: CacheKey, data: Partial<{ trades: ArenaTrade[]; modelChat: ArenaModelChatEntry[]; positions: ArenaPositionsAccount[] }>) => {
      updateData(key, data)
    },
    [updateData],
  )

  // Listen for real-time WebSocket updates
  useEffect(() => {
    if (!wsRef?.current) return

    const handleMessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data)

        // Filter by trading mode/environment first
        const msgEnvironment = msg.trade?.environment || msg.decision?.environment || msg.trading_mode
        if (msgEnvironment && msgEnvironment !== tradingMode) {
          // Ignore messages from different trading environments
          return
        }

        // Only process messages for the active account or all accounts
        const msgAccountId = msg.trade?.account_id || msg.decision?.account_id
        const shouldProcess = activeAccount === 'all' || !msgAccountId || msgAccountId === activeAccount

        if (!shouldProcess) return

        const messageWallet: string | undefined =
          msg.trade?.wallet_address || msg.decision?.wallet_address || undefined
        if (walletAddress) {
          if (!messageWallet) return
          if (messageWallet.toLowerCase() !== walletAddress.toLowerCase()) return
        }

        if (msg.type === 'trade_update' && msg.trade) {
          // Prepend new trade to the list
          setTrades((prev) => {
            // Check if trade already exists to prevent duplicates
            const exists = prev.some((t) => t.trade_id === msg.trade.trade_id)
            if (exists) return prev
            const next = [msg.trade, ...prev].slice(0, DEFAULT_LIMIT)
            writeCache(cacheKey, { trades: next })
            return next
          })
        }

        if (msg.type === 'position_update' && msg.positions) {
          // Update positions for the relevant account
          setPositions((prev) => {
            // If no account_id specified in message, this is a full update for one account
            const accountId = msg.positions[0]?.account_id
            if (!accountId) return msg.positions

            // Replace positions for this specific account
            const otherAccounts = prev.filter((acc) => acc.account_id !== accountId)
            // Find if we have position data in the message
            const newAccountPositions = msg.positions.filter((p: any) => p.account_id === accountId)

            if (newAccountPositions.length > 0) {
              // Construct account snapshot from positions
            const previousMeta = prev.find((acc) => acc.account_id === accountId)
            const accountSnapshot = {
                account_id: accountId,
                account_name: previousMeta?.account_name || '',
                environment: previousMeta?.environment || null,
                available_cash: 0, // Will be updated by next snapshot
                used_margin: previousMeta?.used_margin ?? 0,
                positions_value: previousMeta?.positions_value ?? 0,
                total_unrealized_pnl: 0,
                total_assets: previousMeta?.total_assets ?? 0,
                initial_capital: previousMeta?.initial_capital ?? 0,
                total_return: previousMeta?.total_return ?? null,
                margin_usage_percent: previousMeta?.margin_usage_percent ?? null,
                margin_mode: previousMeta?.margin_mode ?? null,
                positions: newAccountPositions,
              }
              const next = [...otherAccounts, accountSnapshot]
              writeCache(cacheKey, { positions: next })
              return next
            }

            return prev
          })
        }

        if (msg.type === 'model_chat_update' && msg.decision) {
          // Skip WebSocket updates when feed filter is active to prevent overwriting filtered results
          if (isFeedFiltered) return

          emitArenaActivity({
            accountId: msg.decision.account_id,
            exchange: msg.decision.exchange,
            state: 'ai_thinking',
          })

          // Prepend new AI decision to the list
          setModelChat((prev) => {
            // Check if decision already exists to prevent duplicates
            const exists = prev.some((entry) => entry.id === msg.decision.id)
            if (exists) return prev
            const next = [msg.decision, ...prev].slice(0, MODEL_CHAT_LIMIT)
            writeCache(cacheKey, { modelChat: next })
            return next
          })
        }
      } catch (err) {
        console.error('Failed to parse AlphaArenaFeed WebSocket message:', err)
      }
    }

    wsRef.current.addEventListener('message', handleMessage)

    return () => {
      wsRef.current?.removeEventListener('message', handleMessage)
    }
  }, [wsRef, activeAccount, cacheKey, walletAddress, writeCache, isFeedFiltered, emitArenaActivity])

  // Load accounts for dropdown - use dedicated API instead of positions data
  const loadAccounts = useCallback(async () => {
    try {
      setLoadingAccounts(true)
      const accounts = await getAccounts()
      const accountMetas = accounts.map(acc => ({
        account_id: acc.id,
        name: acc.name,
        model: acc.model ?? null,
      }))
      setAllTraderOptions(accountMetas)
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to load accounts:', err)
    } finally {
      setLoadingAccounts(false)
    }
  }, [])

  // Load accounts immediately on mount
  useEffect(() => {
    if (allTraderOptions.length === 0 && !loadingAccounts) {
      loadAccounts()
    }
  }, [])

  // Individual loaders for each data type
  const loadTradesData = useCallback(async () => {
    try {
      setLoadingTrades(true)
      const accountId = activeAccount === 'all' ? undefined : activeAccount
      const symbol = selectedSymbol || undefined
      const exchange = selectedExchange === 'all' ? undefined : selectedExchange
      const tradeRes = await getArenaTrades({
        limit: DEFAULT_LIMIT,
        account_id: accountId,
        trading_mode: tradingMode,
        wallet_address: walletAddress,
        symbol: symbol,
        exchange: exchange,
      })
      const newTrades = tradeRes.trades || []
      setTrades(newTrades)
      updateData(cacheKey, { trades: newTrades })

      // Extract metadata from trades
      if (tradeRes.accounts) {
        const metas = tradeRes.accounts
        setAccountsMeta(prev => {
          const metaMap = new Map(prev.map(m => [m.account_id, m]))
          metas.forEach(m => metaMap.set(m.account_id, m))
          return Array.from(metaMap.values())
        })
        updateData(cacheKey, { accountsMeta: Array.from(new Map(tradeRes.accounts.map(m => [m.account_id, m])).values()) })
      }

      setLoadingTrades(false)
      return tradeRes
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to load trades:', err)
      setLoadingTrades(false)
      return null
    }
  }, [activeAccount, cacheKey, updateData, tradingMode, walletAddress, selectedSymbol, selectedExchange])

  // Helper function to merge and deduplicate model chat entries
  const mergeModelChatData = useCallback((existing: ArenaModelChatEntry[], newData: ArenaModelChatEntry[]) => {
    // Create a Map for fast lookup by id
    const idMap = new Map(existing.map(item => [item.id, item]))

    // Add new data, skip duplicates
    newData.forEach(item => {
      if (!idMap.has(item.id)) {
        idMap.set(item.id, item)
      }
    })

    // Convert back to array and sort by decision_time descending
    return Array.from(idMap.values()).sort((a, b) => {
      const timeA = a.decision_time ? new Date(a.decision_time).getTime() : 0
      const timeB = b.decision_time ? new Date(b.decision_time).getTime() : 0
      return timeB - timeA
    })
  }, [])

  // Helper function to merge and deduplicate program execution logs
  const mergeProgramData = useCallback((existing: ProgramExecutionLog[], newData: ProgramExecutionLog[]) => {
    const idMap = new Map(existing.map(item => [item.id, item]))
    newData.forEach(item => {
      if (!idMap.has(item.id)) {
        idMap.set(item.id, item)
      }
    })
    return Array.from(idMap.values()).sort((a, b) => {
      const timeA = a.created_at ? new Date(a.created_at).getTime() : 0
      const timeB = b.created_at ? new Date(b.created_at).getTime() : 0
      return timeB - timeA
    })
  }, [])

  const loadModelChatData = useCallback(async (isBackgroundRefresh: boolean = false) => {
    // Skip background refresh when feed filter is active
    if (isBackgroundRefresh && isFeedFiltered) return null

    try {
      setLoadingModelChat(true)
      const accountId = activeAccount === 'all' ? undefined : activeAccount
      const symbol = selectedSymbol || undefined
      const exchange = selectedExchange === 'all' ? undefined : selectedExchange
      const chatRes = await getArenaModelChat({
        limit: MODEL_CHAT_LIMIT,
        account_id: accountId,
        trading_mode: tradingMode,
        wallet_address: walletAddress,
        symbol: symbol,
        exchange: exchange,
        after_time: feedAfterTimeUTC,
        before_time: feedBeforeTimeUTC,
        operation: feedAction || undefined,
      })
      const newModelChat = chatRes.entries || []
      const latestEntry = newModelChat[0]

      if (latestEntry?.id) {
        if (latestModelChatIdRef.current !== null && latestEntry.id !== latestModelChatIdRef.current) {
          emitArenaActivity({
            accountId: latestEntry.account_id,
            exchange: latestEntry.exchange,
            state: 'ai_thinking',
          })
        }
        latestModelChatIdRef.current = latestEntry.id
      }

      // If this is a background refresh and user has loaded more history, merge instead of replace
      if (isBackgroundRefresh && modelChat.length > MODEL_CHAT_LIMIT) {
        // Merge new data with existing data, preserving user's loaded history
        const merged = mergeModelChatData(modelChat, newModelChat)
        setModelChat(merged)
        updateData(cacheKey, { modelChat: merged })
        // Keep hasMoreModelChat state unchanged during background refresh
      } else {
        // Initial load or manual refresh: replace all data
        setModelChat(newModelChat)
        updateData(cacheKey, { modelChat: newModelChat })
        // Reset lazy loading state when loading fresh data
        setHasMoreModelChat(newModelChat.length === MODEL_CHAT_LIMIT)
      }

      // Extract metadata from modelchat
      if (chatRes.entries && chatRes.entries.length > 0) {
        const metas = chatRes.entries.map(entry => ({
          account_id: entry.account_id,
          name: entry.account_name,
          model: entry.model ?? null,
        }))
        setAccountsMeta(prev => {
          const metaMap = new Map(prev.map(m => [m.account_id, m]))
          metas.forEach(m => metaMap.set(m.account_id, m))
          return Array.from(metaMap.values())
        })
      }

      setLoadingModelChat(false)
      return chatRes
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to load model chat:', err)
      setLoadingModelChat(false)
      return null
    }

  }, [activeAccount, cacheKey, updateData, tradingMode, walletAddress, modelChat, mergeModelChatData, selectedSymbol, selectedExchange, isFeedFiltered, feedAfterTimeUTC, feedBeforeTimeUTC, feedAction, emitArenaActivity])

  // Load more model chat entries (lazy loading)
  const loadMoreModelChat = useCallback(async () => {
    if (isLoadingMoreModelChat || !hasMoreModelChat || modelChat.length === 0) return

    try {
      setIsLoadingMoreModelChat(true)

      // Get the oldest decision_time from current list
      const oldestEntry = modelChat[modelChat.length - 1]
      const beforeTime = oldestEntry?.decision_time

      if (!beforeTime) {
        setHasMoreModelChat(false)
        setIsLoadingMoreModelChat(false)
        return
      }

      const accountId = activeAccount === 'all' ? undefined : activeAccount
      const exchange = selectedExchange === 'all' ? undefined : selectedExchange
      const chatRes = await getArenaModelChat({
        limit: MODEL_CHAT_LIMIT,
        account_id: accountId,
        trading_mode: tradingMode,
        wallet_address: walletAddress,
        before_time: beforeTime,
        exchange: exchange,
        after_time: feedAfterTimeUTC,
        operation: feedAction || undefined,
      })

      const newEntries = chatRes.entries || []

      // Merge and deduplicate
      const merged = mergeModelChatData(modelChat, newEntries)
      setModelChat(merged)
      updateData(cacheKey, { modelChat: merged })

      // If we got fewer entries than requested, there's no more data
      setHasMoreModelChat(newEntries.length === MODEL_CHAT_LIMIT)

      setIsLoadingMoreModelChat(false)
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to load more model chat:', err)
      setIsLoadingMoreModelChat(false)
    }
  }, [activeAccount, cacheKey, updateData, tradingMode, walletAddress, modelChat, hasMoreModelChat, isLoadingMoreModelChat, mergeModelChatData, selectedSymbol, selectedExchange, feedAfterTimeUTC, feedAction])

  const loadPositionsData = useCallback(async () => {
    try {
      setLoadingPositions(true)
      const accountId = activeAccount === 'all' ? undefined : activeAccount
      const positionRes = await getArenaPositions({ account_id: accountId, trading_mode: tradingMode })
      const newPositions = positionRes.accounts || []
      setPositions(newPositions)
      updateData(cacheKey, { positions: newPositions })

      // Extract metadata from positions
      if (positionRes.accounts) {
        const metas = positionRes.accounts.map(account => ({
          account_id: account.account_id,
          name: account.account_name,
          model: account.model ?? null,
        }))
        setAccountsMeta(prev => {
          const metaMap = new Map(prev.map(m => [m.account_id, m]))
          metas.forEach(m => metaMap.set(m.account_id, m))
          return Array.from(metaMap.values())
        })
        updateData(cacheKey, { accountsMeta: Array.from(new Map(metas.map(m => [m.account_id, m])).values()) })
      }

      setLoadingPositions(false)
      return positionRes
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to load positions:', err)
      setLoadingPositions(false)
      return null
    }
  }, [activeAccount, cacheKey, updateData, tradingMode])

  // Load program execution logs
  const loadProgramData = useCallback(async (backgroundRefresh = false) => {
    // Skip background refresh when feed filter is active
    if (backgroundRefresh && isFeedFiltered) return null

    try {
      if (!backgroundRefresh) setLoadingProgram(true)
      const accountId = activeAccount === 'all' ? undefined : activeAccount
      const env = tradingMode === 'testnet' || tradingMode === 'mainnet' ? tradingMode : undefined
      const exchange = selectedExchange === 'all' ? undefined : selectedExchange
      const logs = await getProgramExecutions({
        account_id: accountId,
        environment: env,
        limit: PROGRAM_LOG_LIMIT,
        exchange: exchange,
        before: feedBeforeTimeUTC,
        after: feedAfterTimeUTC,
        action: feedAction || undefined,
      })
      const latestLog = logs[0]

      if (latestLog?.id) {
        if (latestProgramLogIdRef.current !== null && latestLog.id !== latestProgramLogIdRef.current) {
          emitArenaActivity({
            accountId: latestLog.account_id,
            exchange: latestLog.exchange,
            state: 'program_running',
          })
        }
        latestProgramLogIdRef.current = latestLog.id
      }

      // If background refresh and user has loaded more history, merge instead of replace
      if (backgroundRefresh && programLogs.length > PROGRAM_LOG_LIMIT) {
        const merged = mergeProgramData(programLogs, logs)
        setProgramLogs(merged)
        // Keep hasMoreProgram state unchanged during background refresh
      } else {
        setProgramLogs(logs)
        setHasMoreProgram(logs.length >= PROGRAM_LOG_LIMIT)
      }

      if (!backgroundRefresh) setLoadingProgram(false)
      return logs
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to load program logs:', err)
      if (!backgroundRefresh) setLoadingProgram(false)
      return null
    }
  }, [activeAccount, tradingMode, selectedExchange, programLogs, mergeProgramData, isFeedFiltered, feedAfterTimeUTC, feedBeforeTimeUTC, feedAction, emitArenaActivity])

  // Load more program logs (lazy loading)
  const loadMoreProgramData = useCallback(async () => {
    if (isLoadingMoreProgram || !hasMoreProgram || programLogs.length === 0) return

    try {
      setIsLoadingMoreProgram(true)
      const oldestLog = programLogs[programLogs.length - 1]
      const accountId = activeAccount === 'all' ? undefined : activeAccount
      const env = tradingMode === 'testnet' || tradingMode === 'mainnet' ? tradingMode : undefined
      const exchange = selectedExchange === 'all' ? undefined : selectedExchange
      const moreLogs = await getProgramExecutions({
        account_id: accountId,
        environment: env,
        limit: PROGRAM_LOG_LIMIT,
        before: oldestLog.created_at,
        exchange: exchange,
        after: feedAfterTimeUTC,
        action: feedAction || undefined,
      })

      if (moreLogs.length === 0) {
        setHasMoreProgram(false)
      } else {
        setProgramLogs(prev => [...prev, ...moreLogs])
        setHasMoreProgram(moreLogs.length >= PROGRAM_LOG_LIMIT)
      }
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to load more program logs:', err)
    } finally {
      setIsLoadingMoreProgram(false)
    }
  }, [activeAccount, tradingMode, programLogs, hasMoreProgram, isLoadingMoreProgram, selectedExchange, feedAfterTimeUTC, feedAction])

  // Copy program log content (decision or error based on success status)
  const handleCopyProgramLog = async (log: ProgramExecutionLog) => {
    const content = log.success
      ? JSON.stringify(log.decision_json || {}, null, 2)
      : log.error_message || ''

    const success = await copyToClipboard(content)
    if (success) {
      setCopiedProgramLog(log.id)
      setTimeout(() => setCopiedProgramLog(null), 2000)
    }
  }

  // Copy program log section (Input Data, Data Queries, Execution Logs)
  const handleCopyProgramSection = async (logId: number, section: string, data: any) => {
    const key = `${logId}-${section}`
    const content = JSON.stringify(data, null, 2)
    const success = await copyToClipboard(content)
    if (success) {
      setCopiedProgramSection(key)
      setTimeout(() => setCopiedProgramSection(null), 2000)
    }
  }

  // Lazy load data when tab becomes active
  useEffect(() => {
    const cached = getData(cacheKey)

    if (activeTab === 'trades' && trades.length === 0 && !loadingTrades) {
      if (cached?.trades && cached.trades.length > 0) {
        setTrades(cached.trades)
      } else {
        loadTradesData()
      }
    }

    if (activeTab === 'model-chat' && modelChat.length === 0 && !loadingModelChat) {
      if (cached?.modelChat && cached.modelChat.length > 0) {
        setModelChat(cached.modelChat)
      } else {
        loadModelChatData(false) // false = initial load, not background refresh
      }
    }

    if (activeTab === 'positions' && positions.length === 0 && !loadingPositions) {
      if (cached?.positions && cached.positions.length > 0) {
        setPositions(cached.positions)
      } else {
        loadPositionsData()
      }
    }

    if (activeTab === 'program' && programLogs.length === 0 && !loadingProgram) {
      loadProgramData()
    }
  }, [activeTab, cacheKey])

  // Re-fetch ModelChat and Program data when feed filter changes
  useEffect(() => {
    if (activeTab === 'model-chat' || activeTab === 'program') {
      // Reset lazy loading states
      setHasMoreModelChat(true)
      setHasMoreProgram(true)
      loadModelChatData(false)
      loadProgramData(false)
    }
  }, [feedTimeRange, feedAction, feedCustomFrom, feedCustomTo])

  // Background polling - refresh all data regardless of active tab
  useEffect(() => {
    if (autoRefreshInterval <= 0) return

    const pollAllData = async () => {
      // Load all four APIs in background, independent of active tab
      // For ModelChat, use background refresh mode to preserve loaded history
      await Promise.allSettled([
        loadTradesData(),
        loadModelChatData(true), // true = background refresh, preserve loaded history
        loadPositionsData(),
        loadProgramData(true)    // true = background refresh
      ])
    }

    const intervalId = setInterval(pollAllData, autoRefreshInterval)

    return () => clearInterval(intervalId)
  }, [autoRefreshInterval, loadTradesData, loadModelChatData, loadPositionsData, loadProgramData])

  // Manual refresh trigger handler
  useEffect(() => {
    const shouldForce =
      manualRefreshKey !== prevManualRefreshKey.current ||
      refreshKey !== prevRefreshKey.current

    if (shouldForce) {
      prevManualRefreshKey.current = manualRefreshKey
      prevRefreshKey.current = refreshKey

      // Force refresh all data (manual refresh = full reload, not background refresh)
      Promise.allSettled([
        loadTradesData(),
        loadModelChatData(false), // false = full reload, reset to initial 60 entries
        loadPositionsData(),
        loadProgramData()
      ])
    }
  }, [manualRefreshKey, refreshKey, loadTradesData, loadModelChatData, loadPositionsData, loadProgramData])

  // Reload data when account filter changes
  useEffect(() => {
    // Skip initial mount
    if (prevActiveAccount.current !== activeAccount) {
      prevActiveAccount.current = activeAccount

      // Reset lazy loading state when account changes
      setHasMoreModelChat(true)
      setHasMoreProgram(true)

      // Reload all data with new account filter (full reload, not background refresh)
      Promise.allSettled([
        loadTradesData(),
        loadModelChatData(false), // false = full reload when switching accounts
        loadPositionsData(),
        loadProgramData()
      ])
    }
  }, [activeAccount, loadTradesData, loadModelChatData, loadPositionsData, loadProgramData])

  // Fetch watchlist symbols and filter by current positions
  useEffect(() => {
    const fetchWatchlist = async () => {
      try {
        const response = await getHyperliquidWatchlist();
        const allSymbols = response.symbols || [];

        setSymbolOptions(allSymbols);
        if (selectedSymbol && !allSymbols.includes(selectedSymbol)) {
          setSelectedSymbol(null);
        }
      } catch (err) {
        console.error('Failed to fetch watchlist:', err);
        setSelectedSymbol(null);
      }
    };
    
    fetchWatchlist();
  }, [positions, activeAccount]);



  const accountOptions = useMemo(() => {
    return allTraderOptions.sort((a, b) => a.name.localeCompare(b.name))
  }, [allTraderOptions])

  const handleRefreshClick = async () => {
    setIsRefreshing(true)
    setManualRefreshKey((key) => key + 1)
    // Keep spinning for at least 500ms for visual feedback
    setTimeout(() => setIsRefreshing(false), 500)
  }

  const handleSymbolFilterChange = (symbol: string | null) => {
    setSelectedSymbol(symbol)
    onSelectedSymbolChange?.(symbol)
  }

  const handleExchangeFilterChange = (exchange: 'all' | 'hyperliquid' | 'binance') => {
    setSelectedExchange(exchange)
    onSelectedExchangeChange?.(exchange)
    // Reload data with new exchange filter
    Promise.allSettled([
      loadTradesData(),
      loadModelChatData(false),
      loadProgramData()
    ])
  }

  // Dashboard visibility config handlers
  const handleOpenVisibilityConfig = async () => {
    // Open dialog first with loading state
    setShowVisibilityConfig(true)
    setLoadingVisibilityAccounts(true)
    setVisibilityAccounts([])
    setVisibilityChanges(new Map())
    try {
      const accounts = await getAccounts({ include_hidden: true })
      setVisibilityAccounts(accounts)
    } catch (err) {
      console.error('Failed to load accounts:', err)
    } finally {
      setLoadingVisibilityAccounts(false)
    }
  }

  const handleVisibilityToggle = (accountId: number, show: boolean) => {
    setVisibilityChanges(prev => {
      const next = new Map(prev)
      next.set(accountId, show)
      return next
    })
  }

  const handleSaveVisibility = async () => {
    if (visibilityChanges.size === 0) {
      setShowVisibilityConfig(false)
      return
    }

    setSavingVisibility(true)
    try {
      const updates = Array.from(visibilityChanges.entries()).map(([account_id, show_on_dashboard]) => ({
        account_id,
        show_on_dashboard
      }))
      await updateDashboardVisibility(updates)
      setShowVisibilityConfig(false)
      // Trigger refresh to update chart data
      setManualRefreshKey(key => key + 1)
    } catch (err) {
      console.error('Failed to save visibility settings:', err)
    } finally {
      setSavingVisibility(false)
    }
  }

  const getAccountVisibility = (account: TradingAccount): boolean => {
    if (visibilityChanges.has(account.id)) {
      return visibilityChanges.get(account.id)!
    }
    return account.show_on_dashboard !== false
  }

  const handleAccountFilterChange = (value: number | 'all') => {
    if (selectedAccountProp === undefined) {
      setInternalSelectedAccount(value)
    }
    onSelectedAccountChange?.(value)
    setExpandedChat(null)
    setExpandedSections({})

    // Data reload will be triggered by useEffect when activeAccount updates
  }

  const toggleSection = (entryId: number, section: 'prompt' | 'reasoning' | 'decision') => {
    const key = `${entryId}-${section}`
    setExpandedSections((prev) => ({
      ...prev,
      [key]: !prev[key],
    }))
  }

  const isSectionExpanded = (entryId: number, section: 'prompt' | 'reasoning' | 'decision') =>
    !!expandedSections[`${entryId}-${section}`]

  const handleCopySection = async (entryId: number, section: 'prompt' | 'reasoning' | 'decision', content: string) => {
    const key = `${entryId}-${section}`
    const success = await copyToClipboard(content)
    if (success) {
      setCopiedSections((prev) => ({ ...prev, [key]: true }))
      setTimeout(() => {
        setCopiedSections((prev) => ({ ...prev, [key]: false }))
      }, 2000)
    } else {
      console.error('Failed to copy')
    }
  }

  const isSectionCopied = (entryId: number, section: 'prompt' | 'reasoning' | 'decision') =>
    !!copiedSections[`${entryId}-${section}`]

  const refreshPnlSyncStatus = useCallback(async () => {
    if (tradingMode !== 'testnet' && tradingMode !== 'mainnet') {
      setNeedsSync(false)
      setUnsyncCount(0)
      return
    }

    try {
      const status = await checkPnlSyncStatus(tradingMode)
      setNeedsSync(status.needs_sync)
      setUnsyncCount(status.unsync_count)
    } catch (err) {
      console.error('[AlphaArenaFeed] Failed to check PnL sync status:', err)
    }
  }, [tradingMode])

  useEffect(() => {
    if (activeTab === 'trades') {
      refreshPnlSyncStatus()
    }
  }, [activeTab, refreshPnlSyncStatus])

  // Handle PnL data update
  const handleUpdatePnl = async () => {
    setUpdatingPnl(true)
    setPnlUpdateResult(null)
    try {
      const result = await updateArenaPnl()
      if (result.success) {
        // Calculate total updates across all exchanges and environments
        let totalTrades = 0
        let totalDecisions = 0
        // Process Hyperliquid environments
        if (result.hyperliquid) {
          Object.values(result.hyperliquid).forEach((env) => {
            totalTrades += env.trades_updated + env.trades_created
            totalDecisions += env.decisions_updated + env.program_logs_updated
          })
        }
        // Process Binance environments
        if (result.binance) {
          Object.values(result.binance).forEach((env) => {
            totalTrades += env.trades_updated + env.trades_created
            totalDecisions += env.decisions_updated + env.program_logs_updated
          })
        }
        setPnlUpdateResult(
          t('feed.pnlUpdateSuccess', 'Updated {{trades}} trades, {{decisions}} decisions', {
            trades: totalTrades,
            decisions: totalDecisions,
          })
        )
        await refreshPnlSyncStatus()
        // Refresh trades data to show updated values
        setManualRefreshKey((key) => key + 1)
      } else {
        setPnlUpdateResult(result.message || t('feed.pnlUpdateFailed', 'Update failed'))
      }
    } catch (err) {
      console.error('Failed to update PnL:', err)
      setPnlUpdateResult(t('feed.pnlUpdateError', 'Error updating PnL data'))
    } finally {
      setUpdatingPnl(false)
      // Clear result message after 5 seconds
      setTimeout(() => setPnlUpdateResult(null), 5000)
    }
  }

  // Load snapshots for a specific entry when expanded
  const loadSnapshots = useCallback(async (entryId: number) => {
    // Skip if already cached or loading
    if (snapshotCache.current.has(entryId) || loadingSnapshots.has(entryId)) {
      return
    }

    setLoadingSnapshots((prev) => new Set(prev).add(entryId))

    try {
      const snapshots = await getModelChatSnapshots(entryId)
      snapshotCache.current.set(entryId, snapshots)

      // Update the modelChat entry with snapshot data
      setModelChat((prev) =>
        prev.map((entry) =>
          entry.id === entryId
            ? {
                ...entry,
                prompt_snapshot: snapshots.prompt_snapshot,
                reasoning_snapshot: snapshots.reasoning_snapshot,
                decision_snapshot: snapshots.decision_snapshot,
              }
            : entry
        )
      )
    } catch (err) {
      console.error(`[AlphaArenaFeed] Failed to load snapshots for entry ${entryId}:`, err)
    } finally {
      setLoadingSnapshots((prev) => {
        const next = new Set(prev)
        next.delete(entryId)
        return next
      })
    }
  }, [loadingSnapshots])

  // Get snapshot data for an entry (from cache or entry itself)
  const getSnapshotData = useCallback((entry: ArenaModelChatEntry) => {
    const cached = snapshotCache.current.get(entry.id)
    return {
      prompt_snapshot: cached?.prompt_snapshot ?? entry.prompt_snapshot,
      reasoning_snapshot: cached?.reasoning_snapshot ?? entry.reasoning_snapshot,
      decision_snapshot: cached?.decision_snapshot ?? entry.decision_snapshot,
    }
  }, [])

  // Clear all feed filters
  const clearFeedFilters = useCallback(() => {
    setFeedTimeRange('all')
    setFeedAction('')
    setFeedCustomFrom('')
    setFeedCustomTo('')
    setShowCustomDatePicker(false)
  }, [])

  // Handle time range quick select
  const handleTimeRangeChange = useCallback((range: 'all' | '3d' | '7d' | 'custom') => {
    if (range === 'custom') {
      setShowCustomDatePicker(true)
      setFeedTimeRange('custom')
    } else {
      setShowCustomDatePicker(false)
      setFeedCustomFrom('')
      setFeedCustomTo('')
      setFeedTimeRange(range)
    }
  }, [])

  // Render feed filter bar (shared between ModelChat and Program tabs)
  const renderFeedFilterBar = () => (
    <AlphaArenaFeedFilterBar
      t={t}
      feedTimeRange={feedTimeRange}
      feedAction={feedAction}
      feedCustomFrom={feedCustomFrom}
      feedCustomTo={feedCustomTo}
      showCustomDatePicker={showCustomDatePicker}
      isFeedFiltered={isFeedFiltered}
      onTimeRangeChange={handleTimeRangeChange}
      onActionChange={setFeedAction}
      onCustomFromChange={setFeedCustomFrom}
      onCustomToChange={setFeedCustomTo}
      onClear={clearFeedFilters}
    />
  )

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t('feed.filter', 'Filter')}</span>
          <select
            value={activeAccount === 'all' ? '' : activeAccount}
            onChange={(e) => {
              const value = e.target.value
              handleAccountFilterChange(value ? Number(value) : 'all')
            }}
            className="h-8 rounded border border-border bg-muted px-2 text-xs uppercase tracking-wide text-foreground max-w-[120px]"
          >
            <option value="">{t('feed.allTraders', 'All Traders')}</option>
            {accountOptions.map((meta) => (
              <option key={meta.account_id} value={meta.account_id}>
                {meta.name}
              </option>
            ))}
          </select>
          <select
            value={selectedSymbol || ''}
            onChange={(e) => handleSymbolFilterChange(e.target.value || null)}
            className="h-8 rounded border border-border bg-muted px-2 text-xs uppercase tracking-wide text-foreground"
            disabled={symbolOptions.length === 0}
          >
            <option value="">{t('feed.allSymbols', 'All Symbols')}</option>
            {symbolOptions.map((sym) => (
              <option key={sym} value={sym}>
                {sym}
              </option>
            ))}
          </select>
          <select
            value={selectedExchange}
            onChange={(e) => handleExchangeFilterChange(e.target.value as 'all' | 'hyperliquid' | 'binance')}
            className="h-8 rounded border border-border bg-muted px-2 text-xs uppercase tracking-wide text-foreground"
          >
            <option value="all">{t('feed.allExchanges', 'All Exchanges')}</option>
            <option value="hyperliquid">Hyperliquid</option>
            <option value="binance">Binance</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-7 w-7 p-0" onClick={handleRefreshClick} disabled={isRefreshing || loadingTrades || loadingModelChat || loadingPositions} title={t('common.refresh', 'Refresh')}>
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </Button>
          <Button size="sm" variant="outline" className="h-7 w-7 p-0" onClick={handleOpenVisibilityConfig} title={t('feed.configureVisibility', 'Configure Dashboard Visibility')}>
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <DashboardVisibilityDialog
        open={showVisibilityConfig}
        onOpenChange={setShowVisibilityConfig}
        accounts={visibilityAccounts}
        loading={loadingVisibilityAccounts}
        saving={savingVisibility}
        t={t}
        getAccountVisibility={getAccountVisibility}
        onVisibilityToggle={handleVisibilityToggle}
        onSave={handleSaveVisibility}
      />

      <Tabs
        value={activeTab}
        onValueChange={(value: FeedTab) => setActiveTab(value)}
        className="flex-1 flex flex-col min-h-0"
      >
        <TabsList className="grid grid-cols-4 gap-0 border border-border bg-muted text-foreground">
          <TabsTrigger value="trades" className="data-[state=active]:bg-background data-[state=active]:text-foreground border-r border-border text-[10px] md:text-xs">
            {t('feed.completedTrades', 'COMPLETED TRADES')}
          </TabsTrigger>
          <TabsTrigger value="model-chat" className="data-[state=active]:bg-background data-[state=active]:text-foreground border-r border-border text-[10px] md:text-xs">
            {t('feed.modelChat', 'MODELCHAT')}
          </TabsTrigger>
          <TabsTrigger value="program" className="data-[state=active]:bg-background data-[state=active]:text-foreground border-r border-border text-[10px] md:text-xs">
            {t('feed.program', 'PROGRAM')}
          </TabsTrigger>
          <TabsTrigger value="positions" className="data-[state=active]:bg-background data-[state=active]:text-foreground text-[10px] md:text-xs">
            {t('feed.positions', 'POSITIONS')}
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 border border-t-0 border-border bg-card min-h-0 flex flex-col overflow-hidden">
          {error && (
            <div className="p-4 text-sm text-red-500">
              {error}
            </div>
          )}

          {!error && (
            <>
              <TabsContent value="trades" className="flex-1 h-0 overflow-y-auto mt-0 p-4 space-y-4">
                <AlphaArenaPnlControls
                  t={t}
                  updatingPnl={updatingPnl}
                  pnlUpdateResult={pnlUpdateResult}
                  needsSync={needsSync}
                  unsyncCount={unsyncCount}
                  showPnlConfirm={showPnlConfirm}
                  onShowPnlConfirmChange={setShowPnlConfirm}
                  onConfirmUpdate={handleUpdatePnl}
                  onPageChange={onPageChange}
                />

                {loadingTrades && filteredTrades.length === 0 ? (
                  <div className="text-xs text-muted-foreground">{t('feed.loadingTrades', 'Loading trades...')}</div>
                ) : filteredTrades.length === 0 ? (
                  <div className="text-xs text-muted-foreground">{t('feed.noTrades', 'No recent trades found.')}</div>
                ) : (
                  filteredTrades.map((trade) => {
                    const isNew = !seenTradeIds.current.has(trade.trade_id)
                    if (!seenTradeIds.current.has(trade.trade_id)) {
                      seenTradeIds.current.add(trade.trade_id)
                    }
                    return <AlphaArenaTradeCard key={`${trade.trade_id}-${trade.trade_time}`} trade={trade} isNew={isNew} t={t} />
                  })
                )}
              </TabsContent>

              <TabsContent value="model-chat" className="flex-1 h-0 overflow-y-auto mt-0 p-4 space-y-3">
                {renderFeedFilterBar()}
                {loadingModelChat && filteredModelChat.length === 0 ? (
                  <div className="text-xs text-muted-foreground">{t('feed.loadingModelChat', 'Loading model chat...')}</div>
                ) : filteredModelChat.length === 0 ? (
                  <div className="text-xs text-muted-foreground">{t('feed.noModelChat', 'No recent AI commentary.')}</div>
                ) : (
                  <>
                  {filteredModelChat.map((entry) => {
                    const isExpanded = expandedChat === entry.id
                    const modelLogo = getModelLogo(entry.account_name || entry.model)
                    const isNew = !seenDecisionIds.current.has(entry.id)
                    if (!seenDecisionIds.current.has(entry.id)) {
                      seenDecisionIds.current.add(entry.id)
                    }

                    return (
                      <HighlightWrapper key={entry.id} isNew={isNew}>
                        <button
                          type="button"
                          className="w-full text-left border border-border rounded bg-muted/30 p-4 space-y-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                          onClick={() =>
                            setExpandedChat((current) => {
                              const next = current === entry.id ? null : entry.id
                              if (current === entry.id) {
                                setExpandedSections((prev) => {
                                  const nextState = { ...prev }
                                  Object.keys(nextState).forEach((key) => {
                                    if (key.startsWith(`${entry.id}-`)) {
                                      delete nextState[key]
                                    }
                                  })
                                  return nextState
                                })
                              } else {
                                // Load snapshots when expanding
                                loadSnapshots(entry.id)
                              }
                              return next
                            })
                          }
                        >
                        <div className="flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-wide text-muted-foreground">
                          <div className="flex items-center gap-2">
                            {modelLogo && (
                              <img
                                src={modelLogo.src}
                                alt={modelLogo.alt}
                                className="h-5 w-5 rounded-full object-contain bg-background"
                                loading="lazy"
                              />
                            )}
                            <span className="font-semibold text-foreground">{entry.account_name}</span>
                          </div>
                          <span>{formatDate(entry.decision_time)}</span>
                        </div>
                        <div className="text-sm font-medium text-foreground flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className={`px-2 py-1 rounded text-xs font-bold ${
                              entry.operation?.toUpperCase() === 'BUY'
                                ? 'bg-emerald-100 text-emerald-800'
                                : entry.operation?.toUpperCase() === 'SELL'
                                ? 'bg-red-100 text-red-800'
                                : entry.operation?.toUpperCase() === 'CLOSE'
                                ? 'bg-blue-100 text-blue-800'
                                : entry.operation?.toUpperCase() === 'HOLD'
                                ? 'bg-gray-200 text-gray-800'
                                : 'bg-orange-100 text-orange-800'
                            }`}>
                              {(entry.operation || 'UNKNOWN').toUpperCase()}
                            </span>
                            {entry.symbol && (
                              <span className="font-semibold">{entry.symbol}</span>
                            )}
                            <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                              entry.signal_trigger_id
                                ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400'
                                : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                            }`}>
                              {entry.signal_trigger_id
                                ? t('feed.signalPoolTrigger', 'Signal Pool')
                                : t('feed.scheduledTrigger', 'Scheduled')}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 px-1.5 py-0.5 rounded bg-slate-800/80">
                            <img
                              src={entry.exchange === 'binance' ? '/static/binance_logo.svg' : '/static/hyperliquid_logo.svg'}
                              alt={entry.exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
                              className="h-3.5 w-3.5"
                            />
                            <span className="text-[10px] font-medium text-slate-200">
                              {entry.exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
                            </span>
                          </div>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {isExpanded ? entry.reason : `${entry.reason.slice(0, 160)}${entry.reason.length > 160 ? '…' : ''}`}
                        </div>
                        {isExpanded && (
                          <div className="space-y-2 pt-3">
                            {entry.prompt_template_name && (
                              <div className="flex items-center gap-2 text-xs text-muted-foreground pb-1">
                                <span className="font-medium">{t('feed.promptTemplate', 'Prompt Template')}:</span>
                                <span className="px-2 py-0.5 rounded bg-muted text-foreground font-medium">{entry.prompt_template_name}</span>
                              </div>
                            )}
                            {(() => {
                              const snapshots = getSnapshotData(entry)
                              const isLoadingEntry = loadingSnapshots.has(entry.id)
                              return [{
                                label: t('feed.userPrompt', 'USER PROMPT'),
                                section: 'prompt' as const,
                                content: snapshots.prompt_snapshot,
                                empty: t('feed.noPrompt', 'No prompt available'),
                              }, {
                                label: t('feed.chainOfThought', 'CHAIN OF THOUGHT'),
                                section: 'reasoning' as const,
                                content: snapshots.reasoning_snapshot,
                                empty: t('feed.noReasoning', 'No reasoning available'),
                              }, {
                                label: t('feed.tradingDecisions', 'TRADING DECISIONS'),
                                section: 'decision' as const,
                                content: snapshots.decision_snapshot,
                                empty: t('feed.noDecision', 'No decision payload available'),
                              }].map(({ label, section, content, empty }) => {
                              const open = isSectionExpanded(entry.id, section)
                              const displayContent = content?.trim()
                              const copied = isSectionCopied(entry.id, section)
                              const showLoading = isLoadingEntry && !displayContent
                              
                              return (
                                <div key={section} className="border border-border/60 rounded-md bg-background/60">
                                  <button
                                    type="button"
                                    className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      toggleSection(entry.id, section)
                                    }}
                                  >
                                    <span className="flex items-center gap-2">
                                      <span className="text-xs">{open ? '▼' : '▶'}</span>
                                      {label}
                                    </span>
                                    <span className="text-[10px] text-muted-foreground/80">{open ? t('feed.hideDetails', 'Hide details') : t('feed.showDetails', 'Show details')}</span>
                                  </button>
                                  {open && (
                                    <div
                                      className="border-t border-border/40 bg-muted/40 px-3 py-3 text-xs text-muted-foreground"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      {showLoading ? (
                                        <div className="flex items-center gap-2 text-muted-foreground/70">
                                          <Loader2 className="w-3 h-3 animate-spin" />
                                          <span>{t('feed.loading', 'Loading...')}</span>
                                        </div>
                                      ) : displayContent ? (
                                        <>
                                          <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-foreground/90">
                                            {displayContent}
                                          </pre>
                                          <div className="mt-3 flex justify-end">
                                            <button
                                              type="button"
                                              onClick={(e) => {
                                                e.stopPropagation()
                                                if (displayContent) {
                                                  handleCopySection(entry.id, section, displayContent)
                                                }
                                              }}
                                              className={`px-3 py-1.5 text-[10px] font-medium rounded transition-all ${
                                                copied
                                                  ? 'bg-emerald-500/20 text-emerald-600 border border-emerald-500/30'
                                                  : 'bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground border border-border/60'
                                              }`}
                                            >
                                              {copied ? `✓ ${t('feed.copied', 'Copied')}` : t('feed.copy', 'Copy')}
                                            </button>
                                          </div>
                                        </>
                                      ) : (
                                        <span className="text-muted-foreground/70">{empty}</span>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )
                            })
                            })()}
                          </div>
                        )}
                        <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground uppercase tracking-wide">
                          <span>{t('feed.prevPortion', 'Prev Portion')}: <span className="font-semibold text-foreground">{(entry.prev_portion * 100).toFixed(1)}%</span></span>
                          <span>{t('feed.targetPortion', 'Target Portion')}: <span className="font-semibold text-foreground">{(entry.target_portion * 100).toFixed(1)}%</span></span>
                          <span>{t('feed.totalBalance', 'Total Balance')}: <span className="font-semibold text-foreground">
                            <FlipNumber value={entry.total_balance} prefix="$" decimals={2} />
                          </span></span>
                          <span>{t('feed.executed', 'Executed')}: <span className={`font-semibold ${entry.executed ? 'text-emerald-600' : 'text-amber-600'}`}>{entry.executed ? 'YES' : 'NO'}</span></span>
                        </div>
                        <div className="mt-2 text-[11px] text-primary underline">
                          {isExpanded ? t('feed.clickCollapse', 'Click to collapse') : t('feed.clickExpand', 'Click to expand')}
                        </div>
                        </button>
                      </HighlightWrapper>
                    )
                  })}

                  {/* Load More Button */}
                  {hasMoreModelChat && (
                    <div className="flex justify-center pt-4">
                      <Button
                        onClick={loadMoreModelChat}
                        disabled={isLoadingMoreModelChat}
                        variant="outline"
                        size="sm"
                        className="text-xs"
                      >
                        {isLoadingMoreModelChat ? (
                          <>
                            <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                            {t('feed.loading', 'Loading...')}
                          </>
                        ) : (
                          t('feed.loadMore', 'Load More History')
                        )}
                      </Button>
                    </div>
                  )}

                  {!hasMoreModelChat && modelChat.length > 0 && (
                    <div className="flex justify-center pt-4 text-xs text-muted-foreground">
                      {t('feed.allLoaded', 'All history loaded')}
                    </div>
                  )}
                  </>
                )}
              </TabsContent>

              <TabsContent value="positions" className="flex-1 h-0 overflow-y-auto mt-0 p-4 space-y-4">
                <AlphaArenaPositionsTab loading={loadingPositions} positions={positions} t={t} />
              </TabsContent>

              <TabsContent value="program" className="flex-1 h-0 overflow-y-auto mt-0 p-4 space-y-3">
                <AlphaArenaProgramTab
                  filterBar={renderFeedFilterBar()}
                  loading={loadingProgram}
                  logs={filteredProgramLogs}
                  totalLogsCount={programLogs.length}
                  expandedLog={expandedProgramLog}
                  copiedLog={copiedProgramLog}
                  copiedSection={copiedProgramSection}
                  hasMore={hasMoreProgram}
                  isLoadingMore={isLoadingMoreProgram}
                  t={t}
                  setExpandedLog={setExpandedProgramLog}
                  onCopyLog={handleCopyProgramLog}
                  onCopySection={handleCopyProgramSection}
                  onLoadMore={loadMoreProgramData}
                />
              </TabsContent>
            </>
          )}
        </div>
      </Tabs>
    </div>
  )
}
