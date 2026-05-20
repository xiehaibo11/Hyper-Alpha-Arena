import { apiRequest } from './apiClient'

export interface ManualClosePositionRequest {
  accountId: number
  exchange: 'binance'
  symbol: string
  positionSide?: 'LONG' | 'SHORT' | null
  environment?: string | null
}

export interface ManualClosePositionResponse {
  success: boolean
  account_id: number
  account_name: string
  exchange: string
  environment: string
  symbol: string
  position_side?: 'LONG' | 'SHORT' | 'BOTH' | null
  close_side: 'BUY' | 'SELL'
  closed_size: number
  order_id?: number | string | null
  status?: string | null
  filled_qty?: number | null
  avg_price?: number | null
}

export async function closeManualPosition(
  request: ManualClosePositionRequest,
): Promise<ManualClosePositionResponse> {
  const response = await apiRequest('/manual-trading/close-position', {
    method: 'POST',
    body: JSON.stringify(request),
  })
  return response.json()
}
