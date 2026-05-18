import type { TFunction } from 'i18next'

type FeedTimeRange = 'all' | '3d' | '7d' | 'custom'

interface AlphaArenaFeedFilterBarProps {
  t: TFunction
  feedTimeRange: FeedTimeRange
  feedAction: string
  feedCustomFrom: string
  feedCustomTo: string
  showCustomDatePicker: boolean
  isFeedFiltered: boolean
  onTimeRangeChange: (range: FeedTimeRange) => void
  onActionChange: (action: string) => void
  onCustomFromChange: (value: string) => void
  onCustomToChange: (value: string) => void
  onClear: () => void
}

export default function AlphaArenaFeedFilterBar({
  t,
  feedTimeRange,
  feedAction,
  feedCustomFrom,
  feedCustomTo,
  showCustomDatePicker,
  isFeedFiltered,
  onTimeRangeChange,
  onActionChange,
  onCustomFromChange,
  onCustomToChange,
  onClear,
}: AlphaArenaFeedFilterBarProps) {
  return (
    <div className="flex flex-col gap-2 pb-2 mb-2 border-b border-border">
      <div className="flex items-center gap-1.5 flex-wrap">
        {(['3d', '7d', 'custom'] as const).map(range => (
          <button
            key={range}
            onClick={() => onTimeRangeChange(range)}
            className={`h-6 px-2 text-[10px] font-medium rounded border transition-colors ${
              feedTimeRange === range
                ? 'bg-foreground text-background border-foreground'
                : 'bg-background border-border text-muted-foreground hover:text-foreground hover:border-foreground/50'
            }`}
          >
            {range === '3d' ? t('feed.filterDays3', '3D') :
             range === '7d' ? t('feed.filterDays7', '7D') :
             t('feed.filterCustom', 'Custom')}
          </button>
        ))}

        <div className="w-px h-4 bg-border mx-0.5" />

        <select
          value={feedAction}
          onChange={e => onActionChange(e.target.value)}
          className="h-6 rounded border border-border bg-background px-1.5 text-[10px] font-medium text-foreground uppercase"
        >
          <option value="">{t('feed.filterAllActions', 'All Actions')}</option>
          <option value="buy">BUY</option>
          <option value="sell">SELL</option>
          <option value="hold">HOLD</option>
          <option value="close">CLOSE</option>
        </select>

        {isFeedFiltered && (
          <button
            onClick={onClear}
            className="h-6 px-2 text-[10px] font-medium rounded border border-border text-muted-foreground hover:text-foreground hover:border-foreground/50 transition-colors"
          >
            {t('feed.filterClearAll', 'Clear')}
          </button>
        )}
      </div>

      {showCustomDatePicker && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-muted-foreground">{t('feed.filterFrom', 'From')}</span>
          <input
            type="datetime-local"
            value={feedCustomFrom}
            onChange={e => onCustomFromChange(e.target.value)}
            className="h-6 rounded border border-border bg-background px-1.5 text-[10px] text-foreground"
          />
          <span className="text-[10px] text-muted-foreground">{t('feed.filterTo', 'To')}</span>
          <input
            type="datetime-local"
            value={feedCustomTo}
            onChange={e => onCustomToChange(e.target.value)}
            className="h-6 rounded border border-border bg-background px-1.5 text-[10px] text-foreground"
          />
        </div>
      )}

      {isFeedFiltered && (
        <div className="text-[9px] text-amber-500/80">
          {t('feed.filterAutoRefreshPaused', 'Auto-refresh paused while filter is active')}
        </div>
      )}
    </div>
  )
}
