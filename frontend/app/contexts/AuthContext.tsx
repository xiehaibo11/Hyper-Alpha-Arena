'use client'

import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import Cookies from 'js-cookie'
import { loginUser, getUserProfile, type User as LocalUser, type MembershipInfo } from '@/lib/api'
import type { User as ArenaUser } from '@/lib/auth'

interface AuthContextType {
  user: ArenaUser | null
  loading: boolean
  authEnabled: boolean
  membership: MembershipInfo | null
  membershipLoading: boolean
  setUser: (user: ArenaUser | null) => void
  login: (password: string) => Promise<boolean>
  logout: () => void
  refreshMembership: () => Promise<void>
}

const OWNER_USERNAME = '1019683427@qq.com'
const SESSION_COOKIE = 'arena_session_token'

const AuthContext = createContext<AuthContextType | undefined>(undefined)

function toArenaUser(user: LocalUser): ArenaUser {
  const displayName = user.email || user.username

  return {
    owner: 'local',
    name: user.username,
    createdTime: '',
    updatedTime: '',
    id: String(user.id),
    type: 'local-owner',
    displayName,
    avatar: '',
    email: user.email || user.username,
    phone: '',
    location: '',
    address: [],
    affiliation: '',
    title: '',
    homepage: '',
    bio: '',
    tag: '',
    region: '',
    language: '',
    score: 0,
    isAdmin: true,
    isGlobalAdmin: true,
    isForbidden: !user.is_active,
    signupApplication: 'hyper-alpha-arena',
  }
}

function clearStoredAuth() {
  Cookies.remove(SESSION_COOKIE)
  Cookies.remove('arena_token')
  Cookies.remove('arena_refresh_token')
  Cookies.remove('arena_user')
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ArenaUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [membership, setMembership] = useState<MembershipInfo | null>(null)

  const refreshMembership = async () => {
    setMembership(null)
  }

  const login = async (passwordValue: string) => {
    if (loginLoading) return false

    const trimmedPassword = passwordValue.trim()
    if (!trimmedPassword) {
      setLoginError('Password is required.')
      return false
    }

    setLoginLoading(true)
    setLoginError(null)

    try {
      const response = await loginUser(OWNER_USERNAME, trimmedPassword)
      Cookies.set(SESSION_COOKIE, response.session_token, { expires: 180 })

      const localUser = toArenaUser(response.user)
      Cookies.set('arena_user', JSON.stringify(localUser), { expires: 180 })
      setUser(localUser)
      return true
    } catch (error) {
      console.error('[AuthContext] Local login failed:', error)
      setLoginError('Invalid account password.')
      clearStoredAuth()
      setUser(null)
      return false
    } finally {
      setLoginLoading(false)
    }
  }

  const submitLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await login(password)
  }

  const logout = () => {
    clearStoredAuth()
    setMembership(null)
    setUser(null)
    window.location.href = '/'
  }

  useEffect(() => {
    const initAuth = async () => {
      try {
        const sessionToken = Cookies.get(SESSION_COOKIE)
        if (!sessionToken) {
          clearStoredAuth()
          setUser(null)
          return
        }

        const profile = await getUserProfile(sessionToken)
        const localUser = toArenaUser(profile)
        Cookies.set('arena_user', JSON.stringify(localUser), { expires: 180 })
        setUser(localUser)
      } catch (error) {
        console.warn('[AuthContext] Local session is invalid:', error)
        clearStoredAuth()
        setUser(null)
      } finally {
        setLoading(false)
      }
    }

    initAuth()
  }, [])

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        Loading...
      </div>
    )
  }

  if (!user) {
    return (
      <AuthContext.Provider
        value={{
          user,
          loading,
          authEnabled: true,
          membership,
          membershipLoading: false,
          setUser,
          login,
          logout,
          refreshMembership,
        }}
      >
        <div className="flex h-screen items-center justify-center bg-background px-4">
          <div className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
            <div className="space-y-1">
              <h1 className="text-xl font-semibold">Hyper Alpha Arena</h1>
              <p className="text-sm text-muted-foreground">{OWNER_USERNAME}</p>
            </div>
            <form onSubmit={submitLogin} className="mt-6 space-y-3">
              <input
                type="password"
                autoComplete="current-password"
                autoFocus
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Password"
                className="h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              />
              <button
                type="submit"
                disabled={loginLoading || !password.trim()}
                className="h-10 w-full rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loginLoading ? 'Signing in...' : 'Sign in'}
              </button>
              {loginError && (
                <p className="text-sm text-red-500">{loginError}</p>
              )}
            </form>
          </div>
        </div>
      </AuthContext.Provider>
    )
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        authEnabled: true,
        membership,
        membershipLoading: false,
        setUser,
        login,
        logout,
        refreshMembership,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
