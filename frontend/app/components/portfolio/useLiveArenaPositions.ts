import { useEffect, useMemo, useState } from 'react'
import { getArenaPositions, type ArenaPositionsAccount } from '@/lib/api'
import { useTradingMode } from '@/contexts/TradingModeContext'

const BINANCE_REFRESH_MS = 20_000
const DEFAULT_REFRESH_MS = 12_000
const FIRST_REFRESH_DELAY_MS = 3_000

interface UseLiveArenaPositionsOptions {
  positions: ArenaPositionsAccount[]
  selectedAccount?: number | 'all' | null
  enabled?: boolean
}

export function useLiveArenaPositions({
  positions,
  selectedAccount = 'all',
  enabled = true,
}: UseLiveArenaPositionsOptions) {
  const { tradingMode } = useTradingMode()
  const [livePositions, setLivePositions] = useState<ArenaPositionsAccount[]>(positions)

  const sourceKey = useMemo(
    () => positions
      .map((account) => `${account.account_id}:${account.exchange || 'hyperliquid'}:${account.positions.length}`)
      .join('|'),
    [positions],
  )

  const hasBinance = useMemo(
    () => positions.some((account) => (account.exchange || '').toLowerCase() === 'binance'),
    [positions],
  )

  useEffect(() => {
    setLivePositions(positions)
  }, [positions])

  useEffect(() => {
    if (!enabled || positions.length === 0) return

    let cancelled = false
    const accountId = getRefreshAccountId(positions, selectedAccount)
    const refreshMs = hasBinance ? BINANCE_REFRESH_MS : DEFAULT_REFRESH_MS

    const refresh = async () => {
      if (typeof document !== 'undefined' && document.hidden) return

      try {
        const response = await getArenaPositions({
          account_id: accountId,
          trading_mode: tradingMode,
        })

        if (!cancelled) {
          setLivePositions(response.accounts || [])
        }
      } catch (error) {
        console.error('Failed to refresh live arena positions:', error)
      }
    }

    const firstTimer = window.setTimeout(refresh, FIRST_REFRESH_DELAY_MS)
    const intervalTimer = window.setInterval(refresh, refreshMs)

    return () => {
      cancelled = true
      window.clearTimeout(firstTimer)
      window.clearInterval(intervalTimer)
    }
  }, [enabled, hasBinance, positions, selectedAccount, sourceKey, tradingMode])

  return livePositions
}

function getRefreshAccountId(
  positions: ArenaPositionsAccount[],
  selectedAccount?: number | 'all' | null,
) {
  if (typeof selectedAccount === 'number') return selectedAccount
  if (positions.length === 1) return positions[0].account_id
  return undefined
}
