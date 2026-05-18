import type { TFunction } from 'i18next'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import type { TradingAccount } from '@/lib/api'

interface DashboardVisibilityDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  accounts: TradingAccount[]
  loading: boolean
  saving: boolean
  t: TFunction
  getAccountVisibility: (account: TradingAccount) => boolean
  onVisibilityToggle: (accountId: number, show: boolean) => void
  onSave: () => void
}

export default function DashboardVisibilityDialog({
  open,
  onOpenChange,
  accounts,
  loading,
  saving,
  t,
  getAccountVisibility,
  onVisibilityToggle,
  onSave,
}: DashboardVisibilityDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('feed.dashboardVisibility', 'Dashboard Visibility')}</DialogTitle>
          <DialogDescription>
            {t('feed.dashboardVisibilityDesc', 'Choose which AI Traders to show on the Dashboard.')}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 max-h-[300px] overflow-y-auto py-2">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : accounts.length === 0 ? (
            <div className="text-center text-muted-foreground py-4">
              {t('feed.noAccountsFound', 'No AI Traders found')}
            </div>
          ) : (
            accounts.map(account => (
              <div key={account.id} className="flex items-center justify-between px-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{account.name}</span>
                  {account.model && (
                    <span className="text-xs text-muted-foreground">({account.model})</span>
                  )}
                </div>
                <Switch
                  checked={getAccountVisibility(account)}
                  onCheckedChange={(checked) => onVisibilityToggle(account.id, checked)}
                />
              </div>
            ))
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button onClick={onSave} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {t('common.save', 'Save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
