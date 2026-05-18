import type { TFunction } from 'i18next'
import type { ArenaPositionsAccount } from '@/lib/api'
import FlipNumber from './FlipNumber'

interface AlphaArenaPositionsTabProps {
  loading: boolean
  positions: ArenaPositionsAccount[]
  t: TFunction
}

function formatPercent(value?: number | null) {
  if (value === undefined || value === null) return '—'
  return `${(value * 100).toFixed(2)}%`
}

export default function AlphaArenaPositionsTab({ loading, positions, t }: AlphaArenaPositionsTabProps) {
  if (loading && positions.length === 0) {
    return <div className="text-xs text-muted-foreground">{t('feed.loadingPositions', 'Loading positions...')}</div>
  }

  if (positions.length === 0) {
    return <div className="text-xs text-muted-foreground">{t('feed.noPositions', 'No active positions currently.')}</div>
  }

  return (
    <>
      {positions.map((snapshot) => {
        const marginUsageClass =
          snapshot.margin_usage_percent !== undefined && snapshot.margin_usage_percent !== null
            ? snapshot.margin_usage_percent >= 75
              ? 'text-red-600'
              : snapshot.margin_usage_percent >= 50
                ? 'text-amber-600'
                : 'text-emerald-600'
            : 'text-muted-foreground'

        return (
          <div key={snapshot.account_id} className="border border-border rounded bg-muted/40">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div className="flex items-center gap-3">
                <div className="text-sm font-semibold uppercase tracking-wide text-foreground">
                  {snapshot.account_name}
                </div>
                {snapshot.environment && (
                  <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[11px] uppercase tracking-wide text-muted-foreground">
                    {snapshot.environment}
                  </span>
                )}
                <div className="flex items-center gap-1.5 px-1.5 py-0.5 rounded bg-slate-800/80">
                  <img
                    src={snapshot.exchange === 'binance' ? '/static/binance_logo.svg' : '/static/hyperliquid_logo.svg'}
                    alt={snapshot.exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
                    className="h-3.5 w-3.5"
                  />
                  <span className="text-[10px] font-medium text-slate-200">
                    {snapshot.exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
                  </span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-4 text-xs uppercase tracking-wide text-muted-foreground">
                <div>
                  <span className="block text-[10px] text-muted-foreground">{t('feed.totalEquity', 'Total Equity')}</span>
                  <span className="font-semibold text-foreground">
                    <FlipNumber value={snapshot.total_assets} prefix="$" decimals={2} />
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-muted-foreground">{t('feed.availableCash', 'Available Cash')}</span>
                  <span className="font-semibold text-foreground">
                    <FlipNumber value={snapshot.available_cash} prefix="$" decimals={2} />
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-muted-foreground">{t('feed.usedMargin', 'Used Margin')}</span>
                  <span className="font-semibold text-foreground">
                    <FlipNumber value={snapshot.used_margin ?? 0} prefix="$" decimals={2} />
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-muted-foreground">{t('feed.marginUsage', 'Margin Usage')}</span>
                  <span className={`font-semibold ${marginUsageClass}`}>
                    {snapshot.margin_usage_percent !== undefined && snapshot.margin_usage_percent !== null
                      ? `${snapshot.margin_usage_percent.toFixed(2)}%`
                      : '—'}
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-muted-foreground">{t('feed.unrealizedPnl', 'Unrealized P&L')}</span>
                  <span className={`font-semibold ${snapshot.total_unrealized_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                    <FlipNumber value={snapshot.total_unrealized_pnl} prefix="$" decimals={2} />
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-muted-foreground">{t('feed.totalReturn', 'Total Return')}</span>
                  <span className={`font-semibold ${snapshot.total_return && snapshot.total_return >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                    {formatPercent(snapshot.total_return)}
                  </span>
                </div>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-[980px] divide-y divide-border">
                <thead className="bg-muted/50">
                  <tr className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="px-4 py-2 text-left">{t('feed.side', 'Side')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.coin', 'Coin')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.size', 'Size')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.entryCurrent', 'Entry / Current')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.leverage', 'Leverage')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.marginUsedCol', 'Margin Used')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.notional', 'Notional')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.currentValue', 'Current Value')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.unrealizedPnl', 'Unreal P&L')}</th>
                    <th className="px-4 py-2 text-left">{t('feed.portfolioPercent', 'Portfolio %')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-xs text-muted-foreground">
                  {snapshot.positions.map((position, idx) => {
                    const leverageLabel =
                      position.leverage && position.leverage > 0
                        ? `${position.leverage.toFixed(2)}x`
                        : '—'
                    const marginUsed = position.margin_used ?? 0
                    const roePercent =
                      position.return_on_equity !== undefined && position.return_on_equity !== null
                        ? position.return_on_equity * 100
                        : null
                    const portfolioPercent =
                      position.percentage !== undefined && position.percentage !== null
                        ? position.percentage * 100
                        : null
                    const unrealizedDecimals = Math.abs(position.unrealized_pnl) < 1 ? 4 : 2

                    return (
                      <tr key={`${position.symbol}-${idx}`}>
                        <td className="px-4 py-2 font-semibold text-foreground">{position.side}</td>
                        <td className="px-4 py-2">
                          <div className="font-semibold text-foreground">
                            {position.symbol}
                          </div>
                          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{position.market}</div>
                        </td>
                        <td className="px-4 py-2">
                          <FlipNumber value={position.quantity} decimals={4} />
                        </td>
                        <td className="px-4 py-2">
                          <div className="text-foreground font-semibold">
                            <FlipNumber value={position.avg_cost} prefix="$" decimals={2} />
                          </div>
                          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                            <FlipNumber value={position.current_price} prefix="$" decimals={2} />
                          </div>
                        </td>
                        <td className="px-4 py-2">{leverageLabel}</td>
                        <td className="px-4 py-2">
                          <FlipNumber value={marginUsed} prefix="$" decimals={2} />
                        </td>
                        <td className="px-4 py-2">
                          <FlipNumber value={position.notional} prefix="$" decimals={2} />
                        </td>
                        <td className="px-4 py-2">
                          <FlipNumber value={position.current_value} prefix="$" decimals={2} />
                        </td>
                        <td className={`px-4 py-2 font-semibold ${position.unrealized_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                          <div>
                            <FlipNumber value={position.unrealized_pnl} prefix="$" decimals={unrealizedDecimals} />
                          </div>
                          {roePercent !== null && (
                            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              {roePercent.toFixed(2)}%
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-2">
                          {portfolioPercent !== null ? `${portfolioPercent.toFixed(2)}%` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
    </>
  )
}
