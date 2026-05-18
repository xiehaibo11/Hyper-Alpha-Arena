import type { TFunction } from 'i18next'
import type { ArenaTrade } from '@/lib/api'
import { formatDateTime } from '@/lib/dateTime'
import FlipNumber from './FlipNumber'
import HighlightWrapper from './HighlightWrapper'
import { getModelLogo } from './logoAssets'

interface AlphaArenaTradeCardProps {
  trade: ArenaTrade
  isNew: boolean
  t: TFunction
}

const formatDate = (value?: string | null) => formatDateTime(value, { style: 'short' })

function ProgramSourceIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
      <path d="M508.416 3.584c-260.096 0-243.712 112.64-243.712 112.64l0.512 116.736h248.32v34.816H166.4S0 248.832 0 510.976s145.408 252.928 145.408 252.928h86.528v-121.856S227.328 496.64 374.784 496.64h246.272s138.24 2.048 138.24-133.632V139.776c-0.512 0 20.48-136.192-250.88-136.192zM371.712 82.432c24.576 0 44.544 19.968 44.544 44.544 0 24.576-19.968 44.544-44.544 44.544-24.576 0-44.544-19.968-44.544-44.544-0.512-24.576 19.456-44.544 44.544-44.544z" fill="#E74C3C" />
      <path d="M515.584 1022.464c260.096 0 243.712-112.64 243.712-112.64l-0.512-116.736H510.976V757.76h346.624s166.4 18.944 166.4-243.2-145.408-252.928-145.408-252.928h-86.528v121.856s4.608 145.408-142.848 145.408h-245.76s-138.24-2.048-138.24 133.632v224.768c0-0.512-20.992 135.168 250.368 135.168z m136.704-78.336c-24.576 0-44.544-19.968-44.544-44.544 0-24.576 19.968-44.544 44.544-44.544 24.576 0 44.544 19.968 44.544 44.544 0.512 24.576-19.456 44.544-44.544 44.544z" fill="#F39C12" />
    </svg>
  )
}

function sideClass(side?: string | null) {
  if (side === 'BUY') return 'bg-emerald-100 text-emerald-800'
  if (side === 'SELL') return 'bg-red-100 text-red-800'
  if (side === 'CLOSE') return 'bg-blue-100 text-blue-800'
  if (side === 'HOLD') return 'bg-gray-200 text-gray-800'
  return 'bg-orange-100 text-orange-800'
}

export default function AlphaArenaTradeCard({ trade, isNew, t }: AlphaArenaTradeCardProps) {
  const modelLogo = getModelLogo(trade.account_name || trade.model)
  const exchange = trade.exchange === 'binance' ? 'binance' : 'hyperliquid'

  return (
    <HighlightWrapper key={`${trade.trade_id}-${trade.trade_time}`} isNew={isNew}>
      <div className="border border-border bg-muted/40 rounded px-4 py-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <div className="flex items-center gap-2">
            {modelLogo && (
              <img
                src={modelLogo.src}
                alt={modelLogo.alt}
                className="h-5 w-5 rounded-full object-contain bg-background"
                loading="lazy"
              />
            )}
            <span className="font-semibold text-foreground">{trade.account_name}</span>
          </div>
          <span>{formatDate(trade.trade_time)}</span>
        </div>

        <div className="text-sm text-foreground flex flex-wrap items-center gap-2">
          {trade.decision_source_type === 'program' ? (
            <>
              <ProgramSourceIcon />
              <span className="font-semibold">{trade.prompt_template_name}</span>
            </>
          ) : (
            <span className="font-semibold">{trade.account_name}</span>
          )}
          <span>{t('feed.completedA', 'completed a')}</span>
          <span className={`px-2 py-1 rounded text-xs font-bold ${sideClass(trade.side)}`}>
            {trade.side}
          </span>
          <span>{t('feed.tradeOn', 'trade on')}</span>
          <span className="font-semibold">{trade.symbol}</span>
          <span>!</span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-muted-foreground">
          <div>
            <span className="block text-[10px] uppercase tracking-wide">{t('feed.price', 'Price')}</span>
            <span className="font-medium text-foreground">
              <FlipNumber value={trade.price} prefix="$" decimals={2} />
            </span>
          </div>
          <div>
            <span className="block text-[10px] uppercase tracking-wide">{t('feed.quantity', 'Quantity')}</span>
            <span className="font-medium text-foreground">
              <FlipNumber value={trade.quantity} decimals={4} />
            </span>
          </div>
          <div>
            <span className="block text-[10px] uppercase tracking-wide">{t('feed.notional', 'Notional')}</span>
            <span className="font-medium text-foreground">
              <FlipNumber value={trade.notional} prefix="$" decimals={2} />
            </span>
          </div>
          <div>
            <span className="block text-[10px] uppercase tracking-wide">{t('feed.commission', 'Commission')}</span>
            <span className="font-medium text-foreground">
              <FlipNumber value={trade.commission} prefix="$" decimals={2} />
            </span>
          </div>
        </div>

        {(trade.signal_trigger_id || trade.prompt_template_name) && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground pt-1 border-t border-border/50">
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                trade.signal_trigger_id
                  ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400'
                  : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
              }`}>
                {trade.signal_trigger_id
                  ? t('feed.signalPoolTrigger', 'Signal Pool')
                  : t('feed.scheduledTrigger', 'Scheduled')}
              </span>
              {trade.prompt_template_name && trade.decision_source_type !== 'program' && (
                <span className="px-2 py-0.5 rounded font-medium bg-muted text-foreground">
                  {trade.prompt_template_name}
                </span>
              )}
            </div>
            <div className="flex items-center gap-1.5 px-1.5 py-0.5 rounded bg-slate-800/80">
              <img
                src={exchange === 'binance' ? '/static/binance_logo.svg' : '/static/hyperliquid_logo.svg'}
                alt={exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
                className="h-3.5 w-3.5"
              />
              <span className="text-[10px] font-medium text-slate-200">
                {exchange === 'binance' ? 'Binance' : 'Hyperliquid'}
              </span>
            </div>
          </div>
        )}

        {trade.related_orders && trade.related_orders.length > 0 && (
          <div className="mt-2 pt-2 border-t border-border/50 space-y-1">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
              {t('feed.relatedOrders', 'Related Orders')}
            </div>
            {trade.related_orders.map((order, idx) => (
              <div key={idx} className="flex items-center gap-2 text-xs bg-muted/30 rounded px-2 py-1">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                  order.type === 'sl'
                    ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                }`}>
                  {order.type === 'sl' ? t('feed.stopLoss', 'SL') : t('feed.takeProfit', 'TP')}
                </span>
                <span className="text-muted-foreground">@</span>
                <span className="font-medium">${order.price.toFixed(2)}</span>
                <span className="text-muted-foreground">|</span>
                <span className="text-muted-foreground">{t('feed.qty', 'Qty')}:</span>
                <span className="font-medium">{order.quantity.toFixed(4)}</span>
                <span className="text-muted-foreground">|</span>
                <span className="text-muted-foreground text-[10px]">{formatDate(order.trade_time)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </HighlightWrapper>
  )
}
