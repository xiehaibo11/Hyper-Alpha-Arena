import type { TFunction } from 'i18next'
import { Activity } from 'lucide-react'
import { CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { SignalPool } from './SignalManagerSupport'

interface SignalLogsHeaderProps {
  t: TFunction
  pools: SignalPool[]
  watchlistSymbols: string[]
  logsFilterPool: number | null
  logsFilterSymbol: string
  logsTotal: number
  onPoolChange: (poolId: number | null) => void
  onSymbolChange: (symbol: string) => void
  loadLogsWithFilters: (poolId?: number | null, symbol?: string) => void
}

export default function SignalLogsHeader({
  t,
  pools,
  watchlistSymbols,
  logsFilterPool,
  logsFilterSymbol,
  logsTotal,
  onPoolChange,
  onSymbolChange,
  loadLogsWithFilters,
}: SignalLogsHeaderProps) {
  return (
    <CardHeader className="pb-2">
      <CardTitle className="flex items-center gap-2">
        <Activity className="w-5 h-5" />{t('signals.triggerHistory', 'Trigger History')}
      </CardTitle>
      <div className="flex items-center gap-3 mt-2">
        <Select
          value={logsFilterPool === null ? 'all' : String(logsFilterPool)}
          onValueChange={(value) => {
            const poolId = value === 'all' ? null : Number(value)
            onPoolChange(poolId)
            loadLogsWithFilters(poolId, logsFilterSymbol)
          }}
        >
          <SelectTrigger className="w-[180px] h-8">
            <SelectValue placeholder={t('signals.allPools', 'All Pools')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('signals.allPools', 'All Pools')}</SelectItem>
            {pools.map(pool => (
              <SelectItem key={pool.id} value={String(pool.id)}>{pool.pool_name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={logsFilterSymbol || 'all'}
          onValueChange={(value) => {
            const symbol = value === 'all' ? '' : value
            onSymbolChange(symbol)
            loadLogsWithFilters(logsFilterPool, symbol)
          }}
        >
          <SelectTrigger className="w-[120px] h-8">
            <SelectValue placeholder={t('signals.allSymbols', 'All Symbols')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('signals.allSymbols', 'All Symbols')}</SelectItem>
            {watchlistSymbols.map(symbol => (
              <SelectItem key={symbol} value={symbol}>{symbol}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground ml-auto">
          {t('signals.logsCount', '{{count}} logs', { count: logsTotal })}
        </span>
      </div>
    </CardHeader>
  )
}
