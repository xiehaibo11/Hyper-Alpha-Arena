import type { ExchangeType } from '../../hyperliquid/WalletSelector'

export interface AITrader {
  id: number
  name: string
  model: string
  is_active: boolean | string
}

export interface PositionItem {
  symbol?: string
  size?: number
  entry_price?: number
  mark_price?: number
  position_value?: number
  liquidation_price?: number
  side?: string
  leverage?: number
  unrealized_pnl?: number
  pnl_percentage?: number
}

export interface AIAnalysisPanelProps {
  symbol: string
  period: string
  klines: any[]
  indicators: Record<string, any>
  marketData: any
  selectedIndicators?: string[]
  selectedFlowIndicators?: string[]
  exchange?: ExchangeType
  onAnalysisComplete?: () => void
  accounts?: AITrader[]
}

export interface AnalysisResult {
  success: boolean
  analysis_id?: number
  symbol?: string
  period?: string
  model?: string
  trader_name?: string
  analysis?: string
  created_at?: string
  prompt?: string
  error?: string
}
