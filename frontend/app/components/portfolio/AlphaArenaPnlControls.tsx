import type { TFunction } from 'i18next'
import { Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface AlphaArenaPnlControlsProps {
  t: TFunction
  updatingPnl: boolean
  pnlUpdateResult: string | null
  needsSync: boolean
  unsyncCount: number
  showPnlConfirm: boolean
  onShowPnlConfirmChange: (open: boolean) => void
  onConfirmUpdate: () => void
  onPageChange?: (page: string) => void
}

export default function AlphaArenaPnlControls({
  t,
  updatingPnl,
  pnlUpdateResult,
  needsSync,
  unsyncCount,
  showPnlConfirm,
  onShowPnlConfirmChange,
  onConfirmUpdate,
  onPageChange,
}: AlphaArenaPnlControlsProps) {
  return (
    <>
      <div className="flex items-center justify-between gap-2 pb-2 border-b border-border">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              if (onPageChange) {
                onPageChange('attribution')
                window.location.hash = 'attribution'
              }
            }}
            className="text-xs"
          >
            {t('feed.attributionAnalysis', 'Attribution Analysis')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onShowPnlConfirmChange(true)}
            disabled={updatingPnl}
            className="text-xs"
          >
            {updatingPnl ? (
              <>
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                {t('feed.updatingPnl', 'Updating...')}
              </>
            ) : (
              t('feed.updatePnl', 'Update PnL Data')
            )}
          </Button>
        </div>
        {pnlUpdateResult && (
          <span className="text-xs text-muted-foreground">{pnlUpdateResult}</span>
        )}
      </div>

      {needsSync && (
        <div className="flex items-center gap-3 rounded-lg border border-orange-500/60 bg-orange-500/15 p-3">
          <RefreshCw className="h-4 w-4 flex-shrink-0 text-orange-600 dark:text-orange-400" />
          <p className="flex-1 text-sm text-orange-700 dark:text-orange-300">
            {t('attribution.syncWarning', { count: unsyncCount })}
          </p>
        </div>
      )}

      <Dialog open={showPnlConfirm} onOpenChange={onShowPnlConfirmChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('feed.confirmUpdatePnl', 'Confirm Update PnL Data')}</DialogTitle>
            <DialogDescription>
              {t('feed.confirmUpdatePnlDesc', 'This will fetch the latest fee and PnL data from Hyperliquid API, consuming 2 API calls (testnet + mainnet). Continue?')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => onShowPnlConfirmChange(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button onClick={() => { onShowPnlConfirmChange(false); onConfirmUpdate(); }}>
              {t('common.confirm', 'Confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
