import React, { useCallback, useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom/client'
import Cookies from 'js-cookie'
import { Toaster, toast } from 'react-hot-toast'

import './index.css'
import './i18n'

import { AppMainContent, PAGE_TITLES } from '@/AppPages'
import { AgentWalletUpgradeModal, AuthorizationModal } from '@/components/hyperliquid'
import { HyperAiOnboarding, SplashScreen } from '@/components/hyper-ai'
import Header from '@/components/layout/Header'
import Sidebar from '@/components/layout/Sidebar'
import { ArenaDataProvider } from '@/contexts/ArenaDataContext'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { ExchangeProvider } from '@/contexts/ExchangeContext'
import { TradingModeProvider, useTradingMode } from '@/contexts/TradingModeContext'
import { decodeArenaSession, exchangeCodeForToken, getUserInfo } from '@/lib/auth'
import { useArenaRuntime } from '@/hooks/useArenaRuntime'
import { productConfig, isPageVisible } from '@/lib/productConfig'

window.addEventListener('error', (event) => {
  console.error('Global error caught:', event.error)
  console.error('Error stack:', event.error?.stack)
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled promise rejection:', event.reason)
})

function App() {
  const { tradingMode } = useTradingMode()
  const { setUser: setAuthUser } = useAuth()
  const [currentPage, setCurrentPage] = useState<string>(productConfig.defaultPage)
  const [showSplash, setShowSplash] = useState(true)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [needsHyperAiOnboarding, setNeedsHyperAiOnboarding] = useState(false)
  const [hyperAiConfigChecked, setHyperAiConfigChecked] = useState(false)
  const initStartedRef = useRef(false)

  const handlePageChange = useCallback((page: string) => {
    setCurrentPage(page)
    window.location.hash = page
  }, [])

  const runtime = useArenaRuntime({
    tradingMode,
    currentPage,
    onPageChange: handlePageChange,
  })

  const checkHyperAiConfig = useCallback(async () => {
    try {
      const res = await fetch('/api/hyper-ai/profile')
      const data = await res.json()
      return !data.llm_configured
    } catch (err) {
      console.error('Failed to check Hyper AI config:', err)
      return false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    checkHyperAiConfig()
      .then((needsOnboarding) => {
        if (!cancelled) setNeedsHyperAiOnboarding(needsOnboarding)
      })
      .finally(() => {
        if (!cancelled) setHyperAiConfigChecked(true)
      })

    return () => {
      cancelled = true
    }
  }, [checkHyperAiConfig])

  const handleSplashComplete = useCallback(async () => {
    if (initStartedRef.current) return
    initStartedRef.current = true

    const needsOnboarding = hyperAiConfigChecked
      ? needsHyperAiOnboarding
      : await checkHyperAiConfig()
    setShowOnboarding(needsOnboarding)
    setShowSplash(false)
  }, [checkHyperAiConfig, hyperAiConfigChecked, needsHyperAiOnboarding])

  useEffect(() => {
    const hash = window.location.hash.slice(1)
    const pathname = window.location.pathname

    if (pathname === '/callback') {
      handleAuthCallback(setAuthUser)
      return
    }

    const pageName = extractPageName(hash)
    if (pageName && PAGE_TITLES[pageName] && isPageVisible(pageName)) setCurrentPage(pageName)
  }, [setAuthUser])

  useEffect(() => {
    const onHashChange = () => {
      const pageName = extractPageName(window.location.hash.slice(1))
      if (pageName && PAGE_TITLES[pageName] && isPageVisible(pageName)) setCurrentPage(pageName)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const isHyperAiFirstScreen = currentPage === 'hyper-ai'
  const isDataReady = isHyperAiFirstScreen || !!(
    runtime.user &&
    runtime.account &&
    (runtime.effectiveOverview || tradingMode !== 'paper')
  )

  if (showSplash) {
    return <SplashScreen onComplete={handleSplashComplete} minDuration={700} isReady={isDataReady} />
  }

  if (showOnboarding) {
    return (
      <HyperAiOnboarding
        onComplete={() => setShowOnboarding(false)}
        onSkip={() => setShowOnboarding(false)}
      />
    )
  }

  const pageTitle = PAGE_TITLES[currentPage] ?? PAGE_TITLES.comprehensive

  return (
    <>
      <div className="h-screen flex overflow-hidden">
        <Sidebar
          currentPage={currentPage}
          onPageChange={handlePageChange}
          onAccountUpdated={runtime.handleAccountUpdated}
        />
        <div className="flex-1 flex flex-col min-w-0">
          <Header
            title={pageTitle}
            currentAccount={runtime.account}
            showAccountSelector={currentPage === 'comprehensive'}
          />
          <AppMainContent
            currentPage={currentPage}
            tradingMode={tradingMode}
            account={runtime.account}
            effectiveOverview={runtime.effectiveOverview}
            positions={runtime.positions}
            orders={runtime.orders}
            trades={runtime.trades}
            aiDecisions={runtime.aiDecisions}
            allAssetCurves={runtime.allAssetCurves}
            wsRef={runtime.wsRef}
            hyperliquidRefreshKey={runtime.hyperliquidRefreshKey}
            accountRefreshTrigger={runtime.accountRefreshTrigger}
            accounts={runtime.accounts}
            accountsLoading={runtime.accountsLoading}
            onSwitchUser={runtime.switchUser}
            onSwitchAccount={runtime.switchAccount}
            onAccountUpdated={runtime.handleAccountUpdated}
            onPageChange={handlePageChange}
          />
        </div>
      </div>
      <AuthorizationModal
        isOpen={runtime.authModalOpen}
        onClose={runtime.handleAuthModalClose}
        unauthorizedAccounts={runtime.unauthorizedAccounts}
        onAuthorizationComplete={runtime.handleAuthorizationComplete}
      />
      <AgentWalletUpgradeModal
        isOpen={runtime.agentUpgradeModalOpen}
        onClose={() => runtime.setAgentUpgradeModalOpen(false)}
        walletsToUpgrade={runtime.walletsNeedUpgrade}
        onUpgradeComplete={() => {
          runtime.setAgentUpgradeModalOpen(false)
          runtime.setWalletsNeedUpgrade([])
          runtime.refreshAccounts()
        }}
      />
    </>
  )
}

function extractPageName(hash: string) {
  if (!hash) return null
  const paramIndex = hash.indexOf('?')
  return paramIndex !== -1 ? hash.slice(0, paramIndex) : hash
}

async function handleAuthCallback(setAuthUser: (user: any) => void) {
  try {
    const urlParams = new URLSearchParams(window.location.search)
    const sessionParam = urlParams.get('session')

    if (sessionParam) {
      const session = decodeArenaSession(sessionParam)
      if (!session || !session.token.access_token) {
        console.error('Invalid session payload received')
        toast.error('Login failed: Invalid session payload')
        window.location.href = '/'
        return
      }
      finishLogin(session.token.access_token, session.user, setAuthUser)
      return
    }

    const tokenParam = urlParams.get('token')
    if (tokenParam) {
      console.log('[Callback] Received token from relay server, length:', tokenParam.length)
      try {
        const userData = await getUserInfo(tokenParam)
        if (!userData) {
          console.error('[Callback] Failed to get user information')
          toast.error('Login failed: Unable to get user information')
          window.location.href = '/'
          return
        }
        const refreshTokenParam = urlParams.get('refresh_token')
        if (refreshTokenParam) {
          console.log('[Callback] Saving refresh_token to cookie, length:', refreshTokenParam.length)
          Cookies.set('arena_refresh_token', refreshTokenParam, { expires: 30 })
        }
        finishLogin(tokenParam, userData, setAuthUser)
        return
      } catch (err) {
        console.error('[Callback] Error processing token:', err)
        toast.error('Login failed: Unable to process token')
        window.location.href = '/'
        return
      }
    }

    const code = urlParams.get('code')
    const state = urlParams.get('state')
    if (!code) {
      console.error('No authorization code received')
      toast.error('Login failed: No authorization code received')
      window.location.href = '/'
      return
    }

    const accessToken = await exchangeCodeForToken(code, state || '')
    if (!accessToken) {
      console.error('Failed to get access token')
      toast.error('Login failed: Unable to get access token')
      window.location.href = '/'
      return
    }

    const userData = await getUserInfo(accessToken)
    if (!userData) {
      console.error('Failed to get user information')
      toast.error('Login failed: Unable to get user information')
      window.location.href = '/'
      return
    }
    finishLogin(accessToken, userData, setAuthUser)
  } catch (err) {
    console.error('Callback error:', err)
    toast.error('Login error occurred')
    window.location.href = '/'
  }
}

function finishLogin(accessToken: string, user: any, setAuthUser: (user: any) => void) {
  Cookies.set('arena_token', accessToken, { expires: 7 })
  Cookies.set('arena_user', JSON.stringify(user), { expires: 7 })
  setAuthUser(user)
  toast.success('Login successful!')
  window.location.href = '/'
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <ExchangeProvider>
        <TradingModeProvider>
          <ArenaDataProvider>
            <Toaster position="top-right" />
            <App />
          </ArenaDataProvider>
        </TradingModeProvider>
      </ExchangeProvider>
    </AuthProvider>
  </React.StrictMode>,
)
