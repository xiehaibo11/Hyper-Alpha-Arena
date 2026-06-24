import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'react-hot-toast'

import {
  AIDecision,
  approveBuilder,
  checkMainnetAccounts,
  getAccounts,
  type UnauthorizedAccount,
} from '@/lib/api'
import { checkWalletUpgradeNeeded } from '@/lib/hyperliquidApi'
import type { Account, Order, Overview, Position, Trade, User } from '@/appTypes'

let wsSingleton: WebSocket | null = null

const resolveWsUrl = () => {
  const configuredUrl = import.meta.env.VITE_WS_URL
  if (configuredUrl) return configuredUrl
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

interface UseArenaRuntimeProps {
  tradingMode: string
  currentPage: string
  onPageChange: (page: string) => void
}

export function useArenaRuntime({ tradingMode, currentPage, onPageChange }: UseArenaRuntimeProps) {
  const [user, setUser] = useState<User | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [aiDecisions, setAiDecisions] = useState<AIDecision[]>([])
  const [allAssetCurves, setAllAssetCurves] = useState<any[]>([])
  const [hyperliquidRefreshKey, setHyperliquidRefreshKey] = useState(0)
  const [accountRefreshTrigger, setAccountRefreshTrigger] = useState<number>(0)
  const [accounts, setAccounts] = useState<any[]>([])
  const [accountsLoading, setAccountsLoading] = useState<boolean>(true)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [unauthorizedAccounts, setUnauthorizedAccounts] = useState<UnauthorizedAccount[]>([])
  const [agentUpgradeModalOpen, setAgentUpgradeModalOpen] = useState(false)
  const [walletsNeedUpgrade, setWalletsNeedUpgrade] = useState<any[]>([])
  const authCheckedRef = useRef(false)
  const tradingModeRef = useRef(tradingMode)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    (window as any).__debugShowAuthModal = (mockData?: UnauthorizedAccount[]) => {
      const testAccounts = mockData || [{
        account_id: -999,
        account_name: 'Test Account (Debug)',
        wallet_address: '0x0000000000000000000000000000000000000000',
        max_fee: 0,
        required_fee: 30,
      }]
      const safeAccounts = testAccounts.map((acc, idx) => ({
        ...acc,
        account_id: acc.account_id > 0 ? -(idx + 900) : acc.account_id,
      }))
      setUnauthorizedAccounts(safeAccounts)
      setAuthModalOpen(true)
      console.log('[Debug] Authorization modal opened with SAFE accounts (negative IDs):', safeAccounts)
      console.warn('[Debug] Note: Positive account_ids are converted to negative to prevent affecting real accounts')
    }
    return () => {
      delete (window as any).__debugShowAuthModal
    }
  }, [])

  useEffect(() => {
    tradingModeRef.current = tradingMode
    if (tradingMode !== 'paper') {
      setHyperliquidRefreshKey(prev => prev + 1)
    }
  }, [tradingMode])

  const refreshAccounts = useCallback(async () => {
    try {
      setAccountsLoading(true)
      const list = await getAccounts()
      setAccounts(list)

      const hasOnlyDefaultAccount = list.length === 1 &&
        list[0]?.name === 'Default AI Trader' &&
        list[0]?.api_key === 'default-key-please-update-in-settings'

      if (hasOnlyDefaultAccount && currentPage === 'comprehensive') {
        onPageChange('trader-management')
      }

      if (!authCheckedRef.current) {
        authCheckedRef.current = true
        try {
          const result = await checkMainnetAccounts()
          if (result.unauthorized_accounts && result.unauthorized_accounts.length > 0) {
            const authResults = await Promise.all(
              result.unauthorized_accounts.map(acc =>
                approveBuilder(acc.account_id)
                  .then(res => ({ ...acc, authResult: res }))
                  .catch(err => ({ ...acc, authResult: { success: false, error: err } })),
              ),
            )

            const failedAccounts = authResults.filter(
              item => !item.authResult.success || item.authResult.result?.status === 'err',
            )

            if (failedAccounts.length > 0) {
              setUnauthorizedAccounts(failedAccounts.map(item => ({
                account_id: item.account_id,
                account_name: item.account_name,
                wallet_address: item.wallet_address,
                max_fee: item.max_fee,
                required_fee: item.required_fee,
              })))
              setAuthModalOpen(true)
            }
          }
        } catch (authError) {
          console.error('Failed to check mainnet accounts:', authError)
        }
      }

      try {
        const upgradeResult = await checkWalletUpgradeNeeded()
        if (upgradeResult.count > 0) {
          setWalletsNeedUpgrade(upgradeResult.needsUpgrade)
          setAgentUpgradeModalOpen(true)
        }
      } catch (upgradeError) {
        console.error('Failed to check wallet upgrade:', upgradeError)
      }
    } catch (err) {
      console.error('Failed to fetch accounts', err)
    } finally {
      setAccountsLoading(false)
    }
  }, [currentPage, onPageChange])

  useEffect(() => {
    let reconnectTimer: NodeJS.Timeout | null = null
    let ws = wsSingleton
    const created = !ws || ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED

    const connectWebSocket = () => {
      try {
        ws = new WebSocket(resolveWsUrl())
        wsSingleton = ws
        wsRef.current = ws

        const requestSnapshot = () => {
          ws!.send(JSON.stringify({ type: 'get_snapshot', trading_mode: tradingMode }))
        }
        const requestAssetCurve = () => {
          const env = tradingMode === 'testnet' || tradingMode === 'mainnet' ? tradingMode : undefined
          ws!.send(JSON.stringify({
            type: 'get_asset_curve',
            timeframe: '5m',
            trading_mode: tradingMode,
            ...(env ? { environment: env } : {}),
          }))
        }
        const bumpHyperliquidIfCurrent = (messageMode?: string) => {
          const currentMode = tradingModeRef.current
          if (currentMode !== 'paper' && (messageMode === undefined || messageMode === currentMode)) {
            setHyperliquidRefreshKey(prev => prev + 1)
          }
        }

        const handleOpen = () => {
          console.log('WebSocket connected')
          ws!.send(JSON.stringify({
            type: 'bootstrap',
            username: 'default',
            initial_capital: 10000,
            trading_mode: tradingMode,
          }))
        }

        const handleMessage = (event: MessageEvent) => {
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'bootstrap_ok') {
              if (msg.user) setUser(msg.user)
              if (msg.account) {
                setAccount(msg.account)
                if (tradingMode === 'paper') requestSnapshot()
              }
              refreshAccounts()
            } else if (msg.type === 'snapshot') {
              if (msg.overview) setOverview(msg.overview)
              if (msg.positions) setPositions(msg.positions)
              if (msg.orders) setOrders(msg.orders)
              if (msg.trades) setTrades(msg.trades)
              if (msg.ai_decisions) setAiDecisions(msg.ai_decisions)
              if (msg.all_asset_curves) setAllAssetCurves(msg.all_asset_curves)
              bumpHyperliquidIfCurrent(msg.trading_mode)
            } else if (msg.type === 'trades') {
              setTrades(msg.trades || [])
            } else if (msg.type === 'order_filled') {
              toast.success('Order filled')
              requestSnapshot()
              requestAssetCurve()
            } else if (msg.type === 'order_pending') {
              toast('Order placed, waiting for fill', { icon: '⏳' })
              requestSnapshot()
              requestAssetCurve()
            } else if (msg.type === 'user_switched') {
              setUser(msg.user)
            } else if (msg.type === 'account_switched') {
              setAccount(msg.account)
              refreshAccounts()
            } else if (msg.type === 'trade_update') {
              setTrades(prev => [msg.trade, ...prev].slice(0, 100))
              toast.success('New trade executed!', { duration: 2000 })
            } else if (msg.type === 'position_update') {
              setPositions(msg.positions || [])
            } else if (msg.type === 'model_chat_update') {
              setAiDecisions(prev => [msg.decision, ...prev].slice(0, 100))
            } else if (msg.type === 'asset_curve_update' || msg.type === 'asset_curve_data') {
              setAllAssetCurves(msg.data || [])
              bumpHyperliquidIfCurrent(msg.trading_mode)
            } else if (msg.type === 'error') {
              console.error(msg.message)
              toast.error(msg.message || 'Order error')
            }
          } catch (err) {
            console.error('Failed to parse WebSocket message:', err)
          }
        }

        const handleClose = (event: CloseEvent) => {
          console.log('WebSocket closed:', event.code, event.reason)
          wsSingleton = null
          if (wsRef.current === ws) wsRef.current = null
          if (event.code !== 1000 && event.code !== 1001) {
            reconnectTimer = setTimeout(() => {
              console.log('Attempting to reconnect WebSocket...')
              connectWebSocket()
            }, 3000)
          }
        }

        const handleError = (event: Event) => {
          console.error('WebSocket error:', event)
        }

        ws.addEventListener('open', handleOpen)
        ws.addEventListener('message', handleMessage)
        ws.addEventListener('close', handleClose)
        ws.addEventListener('error', handleError)

        return () => {
          ws?.removeEventListener('open', handleOpen)
          ws?.removeEventListener('message', handleMessage)
          ws?.removeEventListener('close', handleClose)
          ws?.removeEventListener('error', handleError)
        }
      } catch (err) {
        console.error('Failed to create WebSocket:', err)
        reconnectTimer = setTimeout(connectWebSocket, 5000)
      }
    }

    if (created) {
      connectWebSocket()
    } else {
      wsRef.current = ws
    }

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
    // Preserve the original singleton lifecycle; mode-specific refresh happens below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    refreshAccounts()
  }, [accountRefreshTrigger, refreshAccounts])

  useEffect(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && account) {
      const env = tradingMode === 'testnet' || tradingMode === 'mainnet' ? tradingMode : undefined
      wsRef.current.send(JSON.stringify({ type: 'get_snapshot', trading_mode: tradingMode }))
      wsRef.current.send(JSON.stringify({
        type: 'get_asset_curve',
        timeframe: '5m',
        trading_mode: tradingMode,
        ...(env ? { environment: env } : {}),
      }))
    }
  }, [tradingMode, account])

  useEffect(() => {
    const refreshInterval = setInterval(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !account) return
      const env = tradingMode === 'testnet' || tradingMode === 'mainnet' ? tradingMode : undefined
      wsRef.current.send(JSON.stringify({ type: 'get_snapshot', trading_mode: tradingMode }))
      wsRef.current.send(JSON.stringify({
        type: 'get_asset_curve',
        timeframe: '5m',
        trading_mode: tradingMode,
        ...(env ? { environment: env } : {}),
      }))
    }, 300000)

    return () => clearInterval(refreshInterval)
  }, [account, tradingMode])

  const sendWsCommand = useCallback((payload: Record<string, unknown>, errorMessage: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn('WS not connected')
      toast.error('Not connected to server')
      return
    }
    try {
      wsRef.current.send(JSON.stringify(payload))
    } catch (err) {
      console.error(err)
      toast.error(errorMessage)
    }
  }, [])

  const switchUser = useCallback((username: string) => {
    sendWsCommand({ type: 'switch_user', username }, 'Failed to switch user')
  }, [sendWsCommand])

  const switchAccount = useCallback((accountId: number) => {
    sendWsCommand({ type: 'switch_account', account_id: accountId }, 'Failed to switch AI trader')
  }, [sendWsCommand])

  const handleAccountUpdated = useCallback(() => {
    setAccountRefreshTrigger(prev => prev + 1)
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'get_snapshot', trading_mode: tradingMode }))
    }
  }, [tradingMode])

  const handleAuthorizationComplete = useCallback(() => {
    setAuthModalOpen(false)
    setUnauthorizedAccounts([])
    refreshAccounts()
  }, [refreshAccounts])

  const handleAuthModalClose = useCallback(() => {
    setAuthModalOpen(false)
    setUnauthorizedAccounts([])
    refreshAccounts()
  }, [refreshAccounts])

  const effectiveOverview = overview || (tradingMode !== 'paper' ? {
    account: {
      id: 1,
      user_id: 1,
      name: 'Hyperliquid Account',
      account_type: 'AI',
      initial_capital: 0,
      current_cash: 0,
      frozen_cash: 0,
    },
    total_assets: 0,
    positions_value: 0,
  } : null)

  return {
    user,
    account,
    effectiveOverview,
    positions,
    orders,
    trades,
    aiDecisions,
    allAssetCurves,
    hyperliquidRefreshKey,
    accountRefreshTrigger,
    accounts,
    accountsLoading,
    authModalOpen,
    unauthorizedAccounts,
    agentUpgradeModalOpen,
    walletsNeedUpgrade,
    wsRef,
    refreshAccounts,
    switchUser,
    switchAccount,
    handleAccountUpdated,
    handleAuthorizationComplete,
    handleAuthModalClose,
    setAgentUpgradeModalOpen,
    setWalletsNeedUpgrade,
  }
}
