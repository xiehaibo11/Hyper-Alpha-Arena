import type { RefObject } from 'react'

import ArenaAssets from '@/components/arena/ArenaAssets'
import AttributionAnalysis from '@/components/analytics/AttributionAnalysis'
import EventContractPage from '@/components/event-contract/EventContractPage'
import FactorLibrary from '@/components/factor/FactorLibrary'
import { HyperAiPage } from '@/components/hyper-ai'
import { HyperliquidPage } from '@/components/hyperliquid'
import HyperliquidView from '@/components/hyperliquid/HyperliquidView'
import KlinesView from '@/components/klines/KlinesView'
import SystemLogs from '@/components/layout/SystemLogs'
import MobileDashboard from '@/components/mobile/MobileDashboard'
import MobileModelChat from '@/components/mobile/MobileModelChat'
import MobilePrograms from '@/components/mobile/MobilePrograms'
import PremiumFeaturesView from '@/components/premium/PremiumFeaturesView'
import ProgramTrader from '@/components/program/ProgramTrader'
import PromptManager from '@/components/prompt/PromptManager'
import ComprehensiveView from '@/components/portfolio/ComprehensiveView'
import SettingsPage from '@/components/settings/SettingsPage'
import SignalManager from '@/components/signal/SignalManager'
import TraderManagement from '@/components/trader/TraderManagement'
import type { AIDecision } from '@/lib/api'
import type { Account, Order, Overview, Position, Trade } from '@/appTypes'

export const PAGE_TITLES: Record<string, string> = {
  'hyper-ai': 'Hyper AI',
  comprehensive: 'Dashboard',
  'system-logs': 'System Logs',
  'prompt-management': 'Prompt Templates',
  'program-trader': 'Programs',
  'signal-management': 'Signal System',
  'event-contract': 'Event Contract',
  attribution: 'Attribution Analysis',
  'factor-library': 'Factor Library',
  'trader-management': 'AI Trader Management',
  hyperliquid: 'Manual Trading',
  klines: 'K-Line Charts',
  'premium-features': 'Premium Features',
  'model-chat': 'Model Chat',
  settings: 'Settings',
  'arena-assets': 'Arena Assets',
}

interface AppMainContentProps {
  currentPage: string
  tradingMode: string
  account: Account | null
  effectiveOverview: Overview | null
  positions: Position[]
  orders: Order[]
  trades: Trade[]
  aiDecisions: AIDecision[]
  allAssetCurves: any[]
  wsRef: RefObject<WebSocket | null>
  hyperliquidRefreshKey: number
  accountRefreshTrigger: number
  accounts: any[]
  accountsLoading: boolean
  onSwitchUser: (username: string) => void
  onSwitchAccount: (accountId: number) => void
  onAccountUpdated: () => void
  onPageChange: (page: string) => void
}

export function AppMainContent(props: AppMainContentProps) {
  const {
    currentPage,
    tradingMode,
    account,
    effectiveOverview,
    positions,
    orders,
    trades,
    aiDecisions,
    allAssetCurves,
    wsRef,
    hyperliquidRefreshKey,
    accountRefreshTrigger,
    accounts,
    accountsLoading,
    onSwitchUser,
    onSwitchAccount,
    onAccountUpdated,
    onPageChange,
  } = props

  const refreshData = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'get_snapshot',
        trading_mode: tradingMode,
      }))
    }
  }

  return (
    <main className={`flex-1 overflow-hidden flex flex-col min-h-0 min-w-0 ${currentPage === 'hyper-ai' ? '' : 'p-4'}`}>
      <div className={currentPage === 'hyper-ai' ? 'flex flex-col flex-1 min-h-0 min-w-0' : 'hidden'}>
        <HyperAiPage />
      </div>

      {/* Dashboard is now the event-contract view (event-contract-only product) */}
      {currentPage === 'comprehensive' && (
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          <EventContractPage />
        </div>
      )}

      {currentPage === 'system-logs' && <SystemLogs />}
      {currentPage === 'prompt-management' && <PromptManager />}
      {currentPage === 'program-trader' && (
        <>
          <div className="md:hidden flex flex-col flex-1 min-h-0">
            <MobilePrograms />
          </div>
          <div className="hidden md:flex flex-col flex-1 min-h-0">
            <ProgramTrader />
          </div>
        </>
      )}
      {currentPage === 'signal-management' && <SignalManager />}
      {currentPage === 'event-contract' && <EventContractPage />}
      {currentPage === 'attribution' && <AttributionAnalysis />}
      {currentPage === 'factor-library' && <FactorLibrary />}
      {currentPage === 'trader-management' && <TraderManagement />}
      {currentPage === 'hyperliquid' && <HyperliquidPage accountId={account?.id || 1} />}
      {currentPage === 'klines' && <KlinesView onAccountUpdated={onAccountUpdated} />}
      {currentPage === 'premium-features' && (
        <PremiumFeaturesView onAccountUpdated={onAccountUpdated} onPageChange={onPageChange} />
      )}
      {currentPage === 'model-chat' && <MobileModelChat />}
      {currentPage === 'settings' && <SettingsPage />}
      {currentPage === 'arena-assets' && <ArenaAssets />}
    </main>
  )
}
