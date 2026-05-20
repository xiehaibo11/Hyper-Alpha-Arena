import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Loader2, XCircle } from 'lucide-react'
import type { TFunction } from 'i18next'
import type { ArenaPositionsAccount } from '@/lib/api'
import { closeManualPosition } from '@/lib/manualTradingApi'

export interface ManualClosePositionOption {
  key: string
  accountId: number
  accountName: string
  exchange: 'binance'
  environment?: string | null
  symbol: string
  side: string
  quantity: number
  pnl: number
}

interface ManualClosePositionControlProps {
  positions: ArenaPositionsAccount[]
  t: TFunction
  compact?: boolean
  onClosed?: (closed: ManualClosePositionOption) => void
}

export default function ManualClosePositionControl({
  positions,
  t,
  compact = false,
  onClosed,
}: ManualClosePositionControlProps) {
  const options = useMemo(() => buildOptions(positions), [positions])
  const [selectedKey, setSelectedKey] = useState('')
  const [closingKey, setClosingKey] = useState<string | null>(null)
  const selected = options.find((option) => option.key === (selectedKey || options[0]?.key))

  if (options.length === 0) return null

  const handleClose = async () => {
    if (!selected || closingKey) return
    const confirmed = window.confirm(
      t(
        'manualClose.confirm',
        'Confirm close {{exchange}} {{environment}} {{symbol}} {{side}} position for {{account}}?',
        {
          exchange: selected.exchange.toUpperCase(),
          environment: selected.environment || 'mainnet',
          symbol: selected.symbol,
          side: selected.side,
          account: selected.accountName,
        },
      ),
    )
    if (!confirmed) return

    setClosingKey(selected.key)
    try {
      const result = await closeManualPosition({
        accountId: selected.accountId,
        exchange: selected.exchange,
        symbol: selected.symbol,
        positionSide: selected.side === 'SHORT' ? 'SHORT' : 'LONG',
        environment: selected.environment,
      })
      toast.success(
        t('manualClose.success', '{{symbol}} close order submitted', {
          symbol: result.symbol || selected.symbol,
        }),
      )
      onClosed?.(selected)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      toast.error(message || t('manualClose.failed', 'Close position failed'))
    } finally {
      setClosingKey(null)
    }
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? '' : 'rounded border border-border bg-muted/30 px-3 py-2'}`}>
      {!compact && (
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t('manualClose.title', 'Manual Close')}
        </div>
      )}
      <select
        value={selected?.key || ''}
        onChange={(event) => setSelectedKey(event.target.value)}
        className="h-8 min-w-[220px] rounded-md border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-ring"
        disabled={!!closingKey}
      >
        {options.map((option) => (
          <option key={option.key} value={option.key}>
            {option.accountName} · {option.symbol} {option.side} · {option.quantity.toFixed(4)}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={handleClose}
        disabled={!selected || !!closingKey}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-500/40 bg-red-500/10 px-2.5 text-xs font-semibold text-red-600 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {closingKey ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
        {t('manualClose.close', 'Close')}
      </button>
      {selected && (
        <span className={`text-[11px] ${selected.pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
          {selected.pnl >= 0 ? '+' : ''}${selected.pnl.toFixed(Math.abs(selected.pnl) < 1 ? 4 : 2)}
        </span>
      )}
    </div>
  )
}

function buildOptions(positions: ArenaPositionsAccount[]): ManualClosePositionOption[] {
  return positions.flatMap((account) => {
    if ((account.exchange || 'hyperliquid') !== 'binance') return []
    return account.positions
      .filter((position) => Math.abs(position.quantity || 0) > 0)
      .map((position) => ({
        key: `${account.account_id}:binance:${position.symbol}:${position.side}`,
        accountId: account.account_id,
        accountName: account.account_name,
        exchange: 'binance' as const,
        environment: account.environment,
        symbol: position.symbol,
        side: position.side,
        quantity: position.quantity,
        pnl: position.unrealized_pnl || 0,
      }))
  })
}
