import type { TFunction } from 'i18next'
import { ArrowUpDown, BarChart3, Info, Pencil, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { IcBadge, WinRateBadge } from './FactorDisplayHelpers'

interface FactorTableProps {
  rows: any[]
  t: TFunction
  isZh: boolean
  sortCol: string
  getCatLabel: (cat: string) => string
  getFactorDesc: (factor: any) => string
  toggleSort: (col: string) => void
  onAnalyze: (factor: { name: string; displayName: string }) => void
  onEditCustom: (id: number) => void
  onDeleteCustom: (id: number) => void
}

export default function FactorTable({
  rows,
  t,
  isZh,
  sortCol,
  getCatLabel,
  getFactorDesc,
  toggleSort,
  onAnalyze,
  onEditCustom,
  onDeleteCustom,
}: FactorTableProps) {
  return (
    <div className="flex-1 min-h-0 overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 bg-background z-10">
          <TableRow>
            <TableHead>{t('factors.name')}</TableHead>
            <TableHead>{t('factors.category')}</TableHead>
            <TableHead className="text-right">{t('factors.value')} (1h K-line)</TableHead>
            <SortableHead label="IC" active={sortCol === 'ic_mean'} tooltip={t('factors.icTooltip')} onClick={() => toggleSort('ic_mean')} />
            <SortableHead label="ICIR" active={sortCol === 'icir'} tooltip={t('factors.icirTooltip')} onClick={() => toggleSort('icir')} />
            <SortableHead label={t('factors.winRate')} active={sortCol === 'win_rate'} tooltip={t('factors.winRateTooltip')} onClick={() => toggleSort('win_rate')} />
            <InfoHead label={t('factors.decay')} tooltip={t('factors.decayTooltip')} />
            <InfoHead label={t('factors.icTrend')} tooltip={t('factors.icTrendTooltip')} />
            <TableHead className="text-right">{t('factors.samples')}</TableHead>
            <TableHead className="w-24" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(row => (
            <TableRow key={row._isCustom ? `custom-${row._customId}` : row.name}>
              <TableCell>
                <FactorNameCell row={row} t={t} isZh={isZh} getFactorDesc={getFactorDesc} />
              </TableCell>
              <TableCell>
                {row._isCustom ? (
                  <Badge variant="outline" className="text-xs bg-purple-500/10 text-purple-400 border-purple-500/30">
                    {t('factors.customTag')}
                  </Badge>
                ) : (
                  <Badge variant="outline" className="text-xs">{getCatLabel(row.category)}</Badge>
                )}
              </TableCell>
              <TableCell className="text-right font-mono text-sm">
                {row.value != null ? row.value.toFixed(4) : '—'}
              </TableCell>
              <TableCell className="text-right"><IcBadge value={row.ic_mean} /></TableCell>
              <TableCell className="text-right font-mono text-sm">
                {row.icir != null ? row.icir.toFixed(2) : '—'}
              </TableCell>
              <TableCell className="text-right"><WinRateBadge value={row.win_rate} /></TableCell>
              <TableCell className="text-right text-sm">
                {row.decay_half_life != null ? (
                  row.decay_half_life === -1
                    ? <span className="text-blue-400 text-xs">{t('factors.persistent')}</span>
                    : <span className={`font-mono ${row.decay_half_life <= 4 ? 'text-red-400' : row.decay_half_life <= 12 ? 'text-yellow-500' : 'text-green-500'}`}>{row.decay_half_life}h</span>
                ) : <span className="text-muted-foreground">—</span>}
              </TableCell>
              <TableCell className="text-right text-sm">
                {row.ic_trend != null ? (
                  <span className={`font-mono ${row.ic_trend >= 1.2 ? 'text-green-500' : row.ic_trend >= 0.8 ? 'text-yellow-500' : 'text-red-400'}`}>
                    {row.ic_trend.toFixed(2)}x
                  </span>
                ) : <span className="text-muted-foreground">—</span>}
              </TableCell>
              <TableCell className="text-right text-sm">{row.sample_count ?? '—'}</TableCell>
              <TableCell className="text-right">
                <div className="flex gap-0.5 justify-end">
                  <Button variant="ghost" size="sm" className="h-6 w-6 p-0" title={t('factors.analysis.title')}
                    onClick={() => onAnalyze({
                      name: row.name,
                      displayName: row._isCustom ? row.name : (isZh && row.display_name_zh ? row.display_name_zh : row.display_name),
                    })}>
                    <BarChart3 className="h-3 w-3" />
                  </Button>
                  {row._isCustom && (
                    <>
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => onEditCustom(row._customId)}>
                        <Pencil className="h-3 w-3" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-red-500" onClick={() => onDeleteCustom(row._customId)}>
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function SortableHead({ label, active, tooltip, onClick }: { label: string; active: boolean; tooltip: string; onClick: () => void }) {
  return (
    <TableHead className="text-right">
      <Tooltip>
        <TooltipTrigger asChild>
          <button className="inline-flex items-center gap-1 hover:text-foreground" onClick={onClick}>
            {label} {active && <ArrowUpDown className="h-3 w-3" />}
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[220px]"><p className="text-xs">{tooltip}</p></TooltipContent>
      </Tooltip>
    </TableHead>
  )
}

function InfoHead({ label, tooltip }: { label: string; tooltip: string }) {
  return (
    <TableHead className="text-right">
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center gap-1 cursor-help">
            {label} <Info className="h-3 w-3" />
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[280px]"><p className="text-xs">{tooltip}</p></TooltipContent>
      </Tooltip>
    </TableHead>
  )
}

function FactorNameCell({ row, t, isZh, getFactorDesc }: { row: any; t: TFunction; isZh: boolean; getFactorDesc: (factor: any) => string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="font-medium cursor-help flex items-center gap-1">
          {row._isCustom ? row.name : row.display_name}
          <Info className="h-3 w-3 text-muted-foreground" />
        </span>
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-xs">
        {row._isCustom ? (
          <p className="text-xs font-mono">{row._expression}</p>
        ) : (
          <>
            {isZh && row.display_name_zh && <p className="text-xs font-medium mb-1">{row.display_name_zh}</p>}
            <p className="text-xs">{getFactorDesc(row)}</p>
            {row.value_range && (
              <p className="text-xs text-muted-foreground mt-1">{t('factors.range')}: {row.value_range} {row.unit || ''}</p>
            )}
          </>
        )}
      </TooltipContent>
    </Tooltip>
  )
}
