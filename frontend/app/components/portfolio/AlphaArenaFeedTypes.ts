import type React from 'react'

export interface AlphaArenaFeedProps {
  refreshKey?: number
  autoRefreshInterval?: number
  wsRef?: React.MutableRefObject<WebSocket | null>
  selectedAccount?: number | 'all'
  onSelectedAccountChange?: (accountId: number | 'all') => void
  walletAddress?: string
  onPageChange?: (page: string) => void
  onSelectedSymbolChange?: (symbol: string | null) => void
  onSelectedExchangeChange?: (exchange: 'all' | 'hyperliquid' | 'binance') => void
  onArenaActivity?: (activity: {
    accountId: number
    exchange: string
    state: 'program_running' | 'ai_thinking'
  }) => void
}

export type FeedTab = 'trades' | 'model-chat' | 'positions' | 'program'

export const DEFAULT_LIMIT = 100
export const MODEL_CHAT_LIMIT = 60
export const PROGRAM_LOG_LIMIT = 50

export type CacheKey = string
