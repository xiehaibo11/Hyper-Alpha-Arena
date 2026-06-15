import { BarChart3, FileText, NotebookPen, Coins, Bot, Ghost, ScrollText, FlaskConical, ArrowUpDown } from 'lucide-react'
import { KLinesIcon, PremiumIcon, SignalIcon, AttributionIcon } from './navIcons'

export interface NavItem {
  page: string
  i18nKey: string
  fallback: string
  icon: any
}

// Full nav. Sidebar filters this by productConfig.visiblePages.
export const NAV_ITEMS: NavItem[] = [
  { page: 'hyper-ai', i18nKey: 'hyperAi.title', fallback: 'Hyper AI', icon: Bot },
  { page: 'comprehensive', i18nKey: 'sidebar.dashboard', fallback: 'Dashboard', icon: BarChart3 },
  { page: 'trader-management', i18nKey: 'sidebar.aiTrader', fallback: 'AI Trader', icon: Ghost },
  { page: 'prompt-management', i18nKey: 'sidebar.prompts', fallback: 'Prompts', icon: NotebookPen },
  { page: 'program-trader', i18nKey: 'sidebar.programTrader', fallback: 'Program Trader', icon: ScrollText },
  { page: 'signal-management', i18nKey: 'sidebar.signals', fallback: 'Signals', icon: SignalIcon },
  { page: 'event-contract', i18nKey: 'sidebar.eventContract', fallback: 'Event Contract', icon: ArrowUpDown },
  { page: 'attribution', i18nKey: 'sidebar.attribution', fallback: 'Attribution', icon: AttributionIcon },
  { page: 'factor-library', i18nKey: 'sidebar.factorLibrary', fallback: 'Factors', icon: FlaskConical },
  { page: 'hyperliquid', i18nKey: 'sidebar.manualTrading', fallback: 'Manual Trading', icon: Coins },
  { page: 'klines', i18nKey: 'sidebar.klines', fallback: 'K-Lines', icon: KLinesIcon },
  { page: 'premium-features', i18nKey: 'sidebar.premium', fallback: 'Advanced', icon: PremiumIcon },
  { page: 'system-logs', i18nKey: 'sidebar.systemLogs', fallback: 'System Logs', icon: FileText },
]
