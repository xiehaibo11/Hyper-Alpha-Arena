import { useEffect, useState } from 'react'
import type { ExchangeType, WalletOption } from '../../hyperliquid/WalletSelector'
import { getBinancePositions, getHyperliquidPositions } from '@/lib/hyperliquidApi'
import type { PositionItem } from './types'

export function useWalletPositions(exchange: ExchangeType, symbol: string) {
  const [selectedWallet, setSelectedWallet] = useState<WalletOption | null>(null)
  const [positions, setPositions] = useState<PositionItem[]>([])
  const [positionsLoading, setPositionsLoading] = useState(false)

  useEffect(() => {
    setSelectedWallet(null)
    setPositions([])
  }, [exchange])

  useEffect(() => {
    const loadPositions = async () => {
      if (!selectedWallet) {
        setPositions([])
        return
      }

      try {
        setPositionsLoading(true)
        const walletExchange = selectedWallet.exchange || exchange
        const data = walletExchange === 'binance'
          ? await getBinancePositions(selectedWallet.account_id, selectedWallet.environment)
          : await getHyperliquidPositions(selectedWallet.account_id, selectedWallet.environment)

        const mapped = (data.positions || []).map((position: any) => {
          const signedSize = Number(position.szi ?? 0)
          const size = position.sizeAbs ?? Math.abs(signedSize)
          return {
            symbol: position.coin || position.symbol || symbol,
            size,
            entry_price: position.entryPx ?? position.entry_price ?? null,
            mark_price: position.markPx ?? position.mark_price ?? (
              position.positionValue && size ? position.positionValue / size : null
            ),
            position_value: position.positionValue ?? position.position_value ?? null,
            liquidation_price: position.liquidationPx ?? position.liquidation_price ?? null,
            side: position.side || (signedSize > 0 ? 'Long' : (signedSize < 0 ? 'Short' : '')),
            leverage: position.leverage ?? null,
            unrealized_pnl: position.unrealizedPnl ?? position.unrealized_pnl ?? null,
            pnl_percentage: position.pnlPercent ?? position.pnl_percentage ?? null,
          }
        })

        setPositions(mapped)
      } catch (err) {
        console.error('Failed to load positions:', err)
        setPositions([])
      } finally {
        setPositionsLoading(false)
      }
    }

    loadPositions()
  }, [selectedWallet, exchange, symbol])

  return {
    selectedWallet,
    setSelectedWallet,
    positions,
    positionsLoading,
  }
}
