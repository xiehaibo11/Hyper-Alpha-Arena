export interface ContactItem {
  url: string | null
  enabled: boolean
}

export interface ContactConfig {
  twitter: ContactItem
  telegram: ContactItem
  community: ContactItem
}

// Local contact configuration for this deployment.
// The page "Contact Author" entry (sidebar dialog + popover) reads this.
// Telegram points to the operator of this instance so visitors can reach us directly.
const CONTACT_CONFIG: ContactConfig = {
  // Operator's Telegram — visitors can contact us here.
  telegram: { url: 'https://t.me/WhimSeeker', enabled: true },
  // Not configured for this deployment.
  twitter: { url: null, enabled: false },
  community: { url: null, enabled: false },
}

export async function getContactConfig(): Promise<ContactConfig> {
  return CONTACT_CONFIG
}
