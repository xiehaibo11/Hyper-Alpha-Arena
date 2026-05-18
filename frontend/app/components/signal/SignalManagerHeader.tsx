import type { TFunction } from 'i18next'
import { Plus, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TabsList, TabsTrigger } from '@/components/ui/tabs'

interface SignalManagerHeaderProps {
  t: TFunction
  collectionDays: number | null
  onNewSignal: () => void
  onNewPool: () => void
  onOpenAiChat: () => void
}

export default function SignalManagerHeader({
  t,
  collectionDays,
  onNewSignal,
  onNewPool,
  onOpenAiChat,
}: SignalManagerHeaderProps) {
  return (
    <div className="flex items-center justify-between gap-4 mb-4">
      <TabsList className="justify-start">
        <TabsTrigger value="signals" className="min-w-[100px]">{t('signals.tabs.signals', 'Signals')}</TabsTrigger>
        <TabsTrigger value="pools" className="min-w-[120px]">{t('signals.tabs.pools', 'Signal Pools')}</TabsTrigger>
        <TabsTrigger value="wallets" className="min-w-[140px]">{t('signals.tabs.walletTracking', 'Wallet Tracking')}</TabsTrigger>
        <TabsTrigger value="logs" className="min-w-[120px]">{t('signals.tabs.logs', 'Trigger Logs')}</TabsTrigger>
        <TabsTrigger value="regime" className="min-w-[130px]">{t('signals.tabs.regime', 'Market Regime')}</TabsTrigger>
      </TabsList>
      <div className="text-xs">
        <p className="text-amber-600 font-medium flex items-center gap-1">
          <span>⚠️</span>
          <span>{t('signals.mainnetWarning', 'Signal system analyzes Mainnet data only (testnet data unreliable)')}</span>
        </p>
        {collectionDays !== null && collectionDays > 0 && (
          <p className="text-muted-foreground mt-0.5">
            {t('signals.collectionDaysHint', 'Signal backtest relies on market flow data, collected for {{days}} days', { days: collectionDays })}
          </p>
        )}
      </div>
      <div className="flex gap-2">
        <Button onClick={onNewSignal} size="sm">
          <Plus className="w-4 h-4 mr-2" />{t('signals.newSignal', 'New Signal')}
        </Button>
        <Button onClick={onNewPool} size="sm">
          <Plus className="w-4 h-4 mr-2" />{t('signals.newPool', 'New Pool')}
        </Button>
        <Button
          onClick={onOpenAiChat}
          size="sm"
          className="bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 text-white border-0 shadow-lg hover:shadow-xl transition-all"
        >
          <Sparkles className="w-4 h-4 mr-2" />{t('signals.aiSetSignal', 'AI Set Signal')}
        </Button>
      </div>
    </div>
  )
}
