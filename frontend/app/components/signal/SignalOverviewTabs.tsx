import type { TFunction } from 'i18next'
import { SignalDefinitionCard, SignalPoolCard } from './SignalManagerCards'
import type { SignalDefinition, SignalPool } from './SignalManagerSupport'

interface SignalDefinitionsTabProps {
  signals: SignalDefinition[]
  t: TFunction
  onEdit: (signal?: SignalDefinition) => void
  onDelete: (signalId: number) => void
  onBacktest: (signal: SignalDefinition, symbol?: string) => void
}

interface SignalPoolsTabProps {
  pools: SignalPool[]
  signals: SignalDefinition[]
  watchlistSymbols: string[]
  t: TFunction
  onEdit: (pool?: SignalPool) => void
  onDelete: (poolId: number) => void
  onBacktest: (pool: SignalPool, symbol?: string) => void
}

export function SignalDefinitionsTab({ signals, t, onEdit, onDelete, onBacktest }: SignalDefinitionsTabProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {signals.map(signal => (
        <SignalDefinitionCard
          key={signal.id}
          signal={signal}
          t={t}
          onEdit={onEdit}
          onDelete={onDelete}
          onBacktest={onBacktest}
        />
      ))}
    </div>
  )
}

export function SignalPoolsTab({ pools, signals, watchlistSymbols, t, onEdit, onDelete, onBacktest }: SignalPoolsTabProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {pools.map(pool => (
        <SignalPoolCard
          key={pool.id}
          pool={pool}
          signals={signals}
          watchlistSymbols={watchlistSymbols}
          t={t}
          onEdit={onEdit}
          onDelete={onDelete}
          onBacktest={onBacktest}
        />
      ))}
    </div>
  )
}
