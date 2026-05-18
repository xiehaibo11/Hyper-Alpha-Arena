import type { Dispatch, SetStateAction } from 'react'
import type { TFunction } from 'i18next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  BinanceLogo,
  HyperliquidLogo,
  WALLET_EVENT_TYPES,
  formatWalletEventType,
  type PoolSourceType,
  type SignalDefinition,
  type SignalPool,
  type WalletTrackingRuntimeStatus,
} from './SignalManagerSupport'

interface SignalPoolFormState {
  pool_name: string
  signal_ids: number[]
  symbols: string[]
  enabled: boolean
  logic: 'OR' | 'AND'
  exchange: string
  source_type: PoolSourceType
  source_config: {
    addresses: string[]
    event_types: string[]
    sync_mode: string
  }
}

interface SignalPoolDialogProps {
  open: boolean
  editingPool: SignalPool | null
  poolForm: SignalPoolFormState
  setPoolForm: Dispatch<SetStateAction<SignalPoolFormState>>
  signals: SignalDefinition[]
  watchlistSymbols: string[]
  walletRuntime: WalletTrackingRuntimeStatus | null
  savingPool: boolean
  t: TFunction
  onOpenChange: (open: boolean) => void
  onSave: () => void
  loadWatchlist: (exchange?: string) => void
  toggleSignalInPool: (signalId: number) => void
  toggleSymbol: (symbol: string) => void
  toggleWalletAddressInPool: (address: string) => void
  toggleWalletEventType: (eventType: string) => void
}

export default function SignalPoolDialog({
  open,
  editingPool,
  poolForm,
  setPoolForm,
  signals,
  watchlistSymbols,
  walletRuntime,
  savingPool,
  t,
  onOpenChange,
  onSave,
  loadWatchlist,
  toggleSignalInPool,
  toggleSymbol,
  toggleWalletAddressInPool,
  toggleWalletEventType,
}: SignalPoolDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>{editingPool ? t('signals.dialog.editPool', 'Edit Pool') : t('signals.dialog.newPool', 'New Pool')}</DialogTitle>
          <DialogDescription>{t('signals.dialog.configurePool', 'Configure signal pool')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-6 lg:grid-cols-[0.95fr_1.25fr]">
          <div className="space-y-4">
            <div>
              <Label>{t('signals.dialog.poolNameLabel', 'Pool Name')}</Label>
              <Input
                value={poolForm.pool_name}
                onChange={e => setPoolForm(prev => ({ ...prev, pool_name: e.target.value }))}
                placeholder={t('signals.dialog.poolNamePlaceholder', 'e.g., BTC Momentum Pool')}
              />
            </div>
            <div>
              <Label>{t('signals.dialog.sourceTypeLabel', 'Source Type')}</Label>
              <Select
                value={poolForm.source_type}
                onValueChange={(v: PoolSourceType) =>
                  setPoolForm(prev => ({
                    ...prev,
                    source_type: v,
                    logic: v === 'wallet_tracking' ? 'OR' : prev.logic,
                    signal_ids: v === 'market_signals' ? prev.signal_ids : [],
                    symbols: v === 'market_signals' ? prev.symbols : [],
                    source_config: v === 'wallet_tracking'
                      ? {
                          ...prev.source_config,
                          addresses: prev.source_config.addresses || [],
                          event_types: prev.source_config.event_types || ['position_change', 'fill', 'liquidation'],
                          sync_mode: 'ws_only',
                        }
                      : {
                          addresses: [],
                          event_types: ['position_change', 'fill', 'liquidation'],
                          sync_mode: 'ws_only',
                        },
                  }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="market_signals">{t('signals.dialog.marketSignalsType', 'Market Signals')}</SelectItem>
                  <SelectItem value="wallet_tracking">{t('signals.walletTracking.sourceTypeLabel', 'Wallet Tracking')}</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground mt-1">
                {poolForm.source_type === 'wallet_tracking'
                  ? t('signals.walletTracking.poolConfigHint', 'Wallet pools use synced Hyper Insight wallets and real-time event types instead of market indicators.')
                  : t('signals.dialog.marketSignalsTypeHint', 'Market pools continue to use symbols, signal definitions, and exchange-specific trigger logic.')}
              </p>
            </div>
            <div>
              <Label>{t('signals.dialog.exchangeLabel', 'Exchange')}</Label>
              <Select value={poolForm.exchange} onValueChange={v => {
                if (poolForm.source_type === 'market_signals') {
                  const matchingSignalIds = poolForm.signal_ids.filter(id => {
                    const signal = signals.find(s => s.id === id)
                    return signal?.exchange === v
                  })
                  setPoolForm(prev => ({ ...prev, exchange: v, signal_ids: matchingSignalIds }))
                  loadWatchlist(v)
                  return
                }
                setPoolForm(prev => ({ ...prev, exchange: v }))
              }}>
                <SelectTrigger>
                  <SelectValue>
                    <span className="flex items-center gap-2">
                      {poolForm.exchange === 'hyperliquid' ? <HyperliquidLogo /> : <BinanceLogo />}
                      {poolForm.exchange === 'hyperliquid' ? 'Hyperliquid' : 'Binance'}
                    </span>
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="hyperliquid">
                    <span className="flex items-center gap-2"><HyperliquidLogo />Hyperliquid</span>
                  </SelectItem>
                  <SelectItem value="binance">
                    <span className="flex items-center gap-2"><BinanceLogo />Binance</span>
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground mt-1">
                {t('signals.dialog.exchangeDesc', 'Select the target exchange for this pool')}
              </p>
            </div>
            <div className="flex items-center gap-2 pt-2">
              <Switch checked={poolForm.enabled} onCheckedChange={v => setPoolForm(prev => ({ ...prev, enabled: v }))} />
              <Label>{t('signals.dialog.enabledLabel', 'Enabled')}</Label>
            </div>
          </div>

          <div className="space-y-4">
            {poolForm.source_type === 'market_signals' ? (
              <>
                <div>
                  <Label>{t('signals.dialog.symbolsLabel', 'Symbols')}</Label>
                  <div className="flex flex-wrap gap-2 mt-2 rounded-lg border p-3">
                    {watchlistSymbols.length > 0 ? (
                      watchlistSymbols.map(symbol => (
                        <Button
                          key={symbol}
                          variant={poolForm.symbols.includes(symbol) ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => toggleSymbol(symbol)}
                        >
                          {symbol}
                        </Button>
                      ))
                    ) : (
                      <p className="text-sm text-muted-foreground">{t('signals.dialog.noSymbolsInWatchlist', 'No symbols in watchlist. Configure watchlist first.')}</p>
                    )}
                  </div>
                </div>
                <div>
                  <Label>{t('signals.dialog.signalsLabel', 'Signals')}</Label>
                  <div className="space-y-2 mt-2 max-h-48 overflow-y-auto rounded-lg border p-3">
                    {signals.map(signal => {
                      const isMatchingExchange = signal.exchange === poolForm.exchange
                      const isDisabled = !isMatchingExchange
                      return (
                        <div key={signal.id} className={`flex items-center gap-2 ${isDisabled ? 'opacity-50' : ''}`}>
                          <Switch
                            checked={poolForm.signal_ids.includes(signal.id)}
                            onCheckedChange={() => toggleSignalInPool(signal.id)}
                            disabled={isDisabled}
                          />
                          <span className="text-sm flex items-center gap-1.5">
                            {signal.signal_name}
                            {isDisabled && (
                              <span className="inline-flex items-center" title={`${signal.exchange} signal`}>
                                {signal.exchange === 'binance' ? <BinanceLogo /> : <HyperliquidLogo />}
                              </span>
                            )}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
                <div>
                  <Label>{t('signals.dialog.triggerLogicLabel', 'Trigger Logic')}</Label>
                  <Select value={poolForm.logic} onValueChange={(v: 'OR' | 'AND') => setPoolForm(prev => ({ ...prev, logic: v }))}>
                    <SelectTrigger className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="OR">{t('signals.dialog.orLogic', 'OR - Any signal triggers pool')}</SelectItem>
                      <SelectItem value="AND">{t('signals.dialog.andLogic', 'AND - All signals must trigger')}</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    {poolForm.logic === 'AND'
                      ? t('signals.dialog.andLogicDesc', 'Pool triggers only when ALL selected signals meet their conditions simultaneously')
                      : t('signals.dialog.orLogicDesc', 'Pool triggers when ANY selected signal meets its condition')}
                  </p>
                </div>
              </>
            ) : (
              <>
                <div>
                  <Label>{t('signals.walletTracking.addresses', 'Tracked Wallets')}</Label>
                  <div className="mt-2 flex flex-wrap gap-2 rounded-lg border p-3 min-h-[120px] content-start">
                    {walletRuntime?.synced_addresses?.length ? (
                      walletRuntime.synced_addresses.map(address => (
                        <Button
                          key={address}
                          variant={(poolForm.source_config.addresses || []).includes(address) ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => toggleWalletAddressInPool(address)}
                        >
                          {address}
                        </Button>
                      ))
                    ) : (
                      <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground w-full">
                        {t('signals.walletTracking.addressSyncPlaceholder', 'Tracked wallet sync will appear here after the Hyper Insight websocket client is enabled. New synced wallets stay opt-in and are never added to an existing pool automatically.')}
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <Label>{t('signals.walletTracking.eventTypes', 'Event Types')}</Label>
                  <div className="flex flex-wrap gap-2 mt-2 rounded-lg border p-3 min-h-[88px] content-start">
                    {WALLET_EVENT_TYPES.map(eventType => (
                      <Button
                        key={eventType}
                        variant={(poolForm.source_config.event_types || []).includes(eventType) ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => toggleWalletEventType(eventType)}
                      >
                        {formatWalletEventType(t, eventType)}
                      </Button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={savingPool}>{t('signals.dialog.cancel', 'Cancel')}</Button>
          <Button onClick={onSave} disabled={savingPool}>
            {savingPool ? t('signals.dialog.saving', 'Saving...') : t('signals.dialog.save', 'Save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
