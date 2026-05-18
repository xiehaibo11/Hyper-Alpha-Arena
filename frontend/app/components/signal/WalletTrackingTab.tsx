import type { TFunction } from 'i18next'
import { Plus, RefreshCw, Wifi, WifiOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  formatWalletRuntimeTime,
  formatWalletTier,
  type WalletTrackingRuntimeStatus,
} from './SignalManagerSupport'

interface WalletTrackingTabProps {
  t: TFunction
  walletRuntime: WalletTrackingRuntimeStatus | null
  walletRuntimeLoading: boolean
  onEnable: () => void
  onDisable: () => void
  onCreateWalletPool: () => void
}

export default function WalletTrackingTab({
  t,
  walletRuntime,
  walletRuntimeLoading,
  onEnable,
  onDisable,
  onCreateWalletPool,
}: WalletTrackingTabProps) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('signals.walletTracking.title', 'Wallet Tracking')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="rounded-lg border bg-muted/30 p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-medium">{t('signals.walletTracking.connectionStatus', 'Connection Status')}</div>
                  <div className="text-xs text-muted-foreground">{t('signals.walletTracking.connectionHint', 'Enable Hyper Insight sync here. HAA will keep synced wallets available for pool selection and runtime matching.')}</div>
                </div>
                <span className={`text-xs px-2 py-1 rounded inline-flex items-center gap-1 ${
                  walletRuntime?.status === 'connected'
                    ? 'bg-emerald-500/10 text-emerald-600'
                    : walletRuntime?.enabled
                      ? 'bg-amber-500/10 text-amber-600'
                      : 'bg-muted text-muted-foreground'
                }`}>
                  {walletRuntime?.status === 'connected'
                    ? <Wifi className="w-3 h-3" />
                    : walletRuntime?.enabled
                      ? <RefreshCw className="w-3 h-3 animate-spin" />
                      : <WifiOff className="w-3 h-3" />}
                  {walletRuntime?.status === 'connected'
                    ? ((walletRuntime?.synced_addresses?.length || 0) > 0
                      ? t('signals.walletTracking.connected', 'Connected')
                      : t('signals.walletTracking.connectedNoWallets', 'Connected · No tracked wallets'))
                    : walletRuntime?.status === 'waiting_for_token'
                      ? t('signals.walletTracking.waitingForToken', 'Waiting for token')
                      : walletRuntime?.enabled
                          ? t('signals.walletTracking.connecting', 'Connecting')
                          : t('signals.walletTracking.notConnected', 'Not Connected')}
                </span>
              </div>
              <div className="mt-3 grid gap-2 text-xs text-muted-foreground">
                <div>{t('signals.walletTracking.tier', 'Tier')}: <span className="text-foreground">{formatWalletTier(t, walletRuntime?.tier)}</span></div>
                <div>{t('signals.walletTracking.syncedWalletCount', 'Synced wallets')}: <span className="text-foreground">{walletRuntime?.synced_addresses?.length || 0}</span></div>
                <div>{t('signals.walletTracking.lastEventAt', 'Last event')}: <span className="text-foreground">{formatWalletRuntimeTime(walletRuntime?.last_event_at)}</span></div>
              </div>
              {walletRuntime?.last_error && (
                <div className="mt-3 text-xs text-red-500">
                  {t('signals.walletTracking.lastError', 'Last error')}: {walletRuntime.last_error}
                </div>
              )}
            </div>

            <div className="rounded-lg border p-4 space-y-3">
              <div className="text-sm font-medium">{t('signals.walletTracking.syncedWallets', 'Synced Wallets')}</div>
              {walletRuntimeLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  {t('signals.walletTracking.loading', 'Loading...')}
                </div>
              ) : walletRuntime?.synced_addresses?.length ? (
                <div className="flex flex-wrap gap-2">
                  {walletRuntime.synced_addresses.map(address => (
                    <span key={address} className="rounded-md border px-2 py-1 text-xs">
                      {address}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t('signals.walletTracking.noSyncedWallets', 'No synced wallets yet. Track wallets on Hyper Insight first.')}
                </p>
              )}
            </div>
          </div>

          <div className="flex gap-2">
            <Button asChild variant="outline" size="sm">
              <a href="https://hyper.akooi.com/" target="_blank" rel="noopener noreferrer">
                {t('signals.walletTracking.manageOnInsight', 'Manage on Hyper Insight')}
              </a>
            </Button>
            {walletRuntime?.enabled ? (
              <Button onClick={onDisable} size="sm" variant="outline" disabled={walletRuntimeLoading}>
                {t('signals.walletTracking.disable', 'Disable Sync')}
              </Button>
            ) : (
              <Button onClick={onEnable} size="sm" disabled={walletRuntimeLoading}>
                {t('signals.walletTracking.enable', 'Enable Sync')}
              </Button>
            )}
            <Button onClick={onCreateWalletPool} size="sm">
              <Plus className="w-4 h-4 mr-2" />
              {t('signals.walletTracking.createWalletPool', 'Create Wallet Pool')}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            {t('signals.walletTracking.inlineHint', 'Connect here first. Once tracked wallets appear, choose which ones should enter HAA signal pools.')}
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
