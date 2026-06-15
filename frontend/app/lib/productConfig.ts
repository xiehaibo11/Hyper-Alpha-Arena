// Product focus configuration. Driven by VITE_PRODUCT_MODE so this dedicated
// client repo ships as an event-contract product by default, while 'full'
// keeps every page for internal development.
type ProductMode = 'event_contract' | 'full'

const MODE = (import.meta.env.VITE_PRODUCT_MODE as ProductMode) || 'event_contract'

const EVENT_CONTRACT_PAGES = ['event-contract', 'hyper-ai', 'settings']

export const productConfig = {
  mode: MODE,
  // null => all pages visible (full mode)
  visiblePages: MODE === 'event_contract' ? EVENT_CONTRACT_PAGES : null as string[] | null,
  defaultPage: MODE === 'event_contract' ? 'event-contract' : 'hyper-ai',
  showExchangeSelector: MODE !== 'event_contract',
  showTradingModeToggle: MODE !== 'event_contract',
}

export function isPageVisible(page: string): boolean {
  return productConfig.visiblePages === null || productConfig.visiblePages.includes(page)
}
