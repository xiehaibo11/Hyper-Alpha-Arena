import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  AlertCircle,
  Bot,
  Brain,
  CheckCircle2,
  ChevronDown,
  Loader2,
  X,
} from 'lucide-react'
import type { ChatImageAttachment } from './HyperAiChatTypes'

export const MAX_IMAGE_ATTACHMENTS = 4
export const MAX_IMAGE_BYTES = 6 * 1024 * 1024

export interface CompressionPoint {
  message_id: number
  summary: string
  compressed_at: string
}

export interface SkillInfo {
  name: string
  description: string
  description_zh: string
  command: string
  enabled: boolean
}

export function readImageAttachment(file: File): Promise<ChatImageAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      if (!result) {
        reject(new Error('Empty image data'))
        return
      }
      resolve({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        name: file.name || 'pasted-image',
        mime_type: file.type || 'image/png',
        data_url: result,
        size: file.size,
      })
    }
    reader.onerror = () => reject(reader.error || new Error('Failed to read image'))
    reader.readAsDataURL(file)
  })
}

export interface TokenUsage {
  current_tokens: number
  max_tokens: number
  usage_ratio: number
  show_warning: boolean
}

export interface LLMProvider {
  id: string
  name: string
  models: string[]
  base_url?: string
}

// Memory category icons and colors
const MEMORY_CATEGORY_STYLES: Record<string, { icon: string; color: string }> = {
  preference: { icon: '🎯', color: 'text-blue-500' },
  decision: { icon: '⚡', color: 'text-amber-500' },
  lesson: { icon: '📖', color: 'text-green-500' },
  insight: { icon: '💡', color: 'text-purple-500' },
  context: { icon: '📌', color: 'text-gray-500' },
}

// Memory Modal component - read-only view of AI memories
export function MemoryModal({
  open,
  onClose
}: {
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [memories, setMemories] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open) {
      setLoading(true)
      fetch('/api/hyper-ai/memories?limit=50')
        .then(res => res.json())
        .then(data => setMemories(data.memories || []))
        .catch(() => setMemories([]))
        .finally(() => setLoading(false))
    }
  }, [open])

  if (!open) return null

  // Group memories by category
  const grouped: Record<string, any[]> = {}
  for (const m of memories) {
    const cat = m.category || 'context'
    if (!grouped[cat]) grouped[cat] = []
    grouped[cat].push(m)
  }

  const categoryOrder = ['preference', 'decision', 'lesson', 'insight', 'context']

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="w-full max-w-3xl bg-background rounded-lg shadow-xl flex flex-col"
           style={{ height: '600px' }}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold">
              {t('hyperAi.memory.title', 'What Hyper AI Remembered')}
            </h2>
            {memories.length > 0 && (
              <span className="text-xs text-muted-foreground ml-2">
                {t('hyperAi.memory.items', '{{count}} memories', { count: memories.length })}
              </span>
            )}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : memories.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Brain className="w-12 h-12 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground max-w-sm">
                {t('hyperAi.memory.empty')}
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {categoryOrder.map(cat => {
                const items = grouped[cat]
                if (!items || items.length === 0) return null
                const style = MEMORY_CATEGORY_STYLES[cat] || MEMORY_CATEGORY_STYLES.context
                const label = t(`hyperAi.memory.category.${cat}`, cat)
                return (
                  <div key={cat}>
                    <div className="flex items-center gap-2 mb-2">
                      <span>{style.icon}</span>
                      <span className={`text-sm font-medium ${style.color}`}>{label}</span>
                      <span className="text-xs text-muted-foreground">({items.length})</span>
                    </div>
                    <div className="space-y-2 ml-6">
                      {items.map((m: any) => (
                        <MemoryItem key={m.id} memory={m} />
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MemoryItem({ memory }: { memory: any }) {
  const importance = memory.importance || 0.5
  const stars = Math.round(importance * 5)
  const date = memory.created_at
    ? new Date(memory.created_at).toLocaleDateString()
    : ''

  return (
    <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
      <p className="leading-relaxed">{memory.content}</p>
      <div className="flex items-center gap-3 mt-1.5 text-xs text-muted-foreground">
        <span>{'★'.repeat(stars)}{'☆'.repeat(5 - stars)}</span>
        {date && <span>{date}</span>}
        {memory.source && <span className="capitalize">{memory.source}</span>}
      </div>
    </div>
  )
}

// LLM Config Modal component
export function LLMConfigModal({
  open,
  onClose,
  providers,
  currentProfile,
  onSaved
}: {
  open: boolean
  onClose: () => void
  providers: LLMProvider[]
  currentProfile: any
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const [selectedProvider, setSelectedProvider] = useState(currentProfile?.llm_provider || '')
  const [apiKey, setApiKey] = useState('')
  const [modelInput, setModelInput] = useState(currentProfile?.llm_model || '')
  const [customBaseUrl, setCustomBaseUrl] = useState(currentProfile?.llm_base_url || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const currentProvider = providers.find(p => p.id === selectedProvider)

  useEffect(() => {
    if (open) {
      setSelectedProvider(currentProfile?.llm_provider || '')
      setModelInput(currentProfile?.llm_model || '')
      setCustomBaseUrl(currentProfile?.llm_base_url || '')
      setApiKey('')
      setError('')
      setSuccess(false)
    }
  }, [open, currentProfile])

  // When provider changes, set default model if current model is empty
  useEffect(() => {
    if (selectedProvider && !modelInput) {
      const provider = providers.find(p => p.id === selectedProvider)
      if (provider && provider.models.length > 0) {
        setModelInput(provider.models[0])
      }
    }
  }, [selectedProvider])

  const handleSave = async () => {
    if (!selectedProvider || !apiKey) {
      setError(t('hyperAi.onboarding.fillRequired', 'Please fill in all required fields'))
      return
    }

    if (selectedProvider === 'custom' && !customBaseUrl) {
      setError(t('hyperAi.onboarding.baseUrlRequired', 'Base URL is required for custom provider'))
      return
    }

    setSaving(true)
    setError('')

    try {
      const res = await fetch('/api/hyper-ai/profile/llm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: selectedProvider,
          api_key: apiKey,
          model: modelInput,
          base_url: selectedProvider === 'custom' ? customBaseUrl : undefined
        })
      })

      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Connection test failed')
      }

      setSuccess(true)
      setTimeout(() => {
        onSaved()
        onClose()
      }, 800)
    } catch (e: any) {
      setError(e.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="w-full max-w-md bg-background rounded-lg shadow-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t('hyperAi.configTitle', 'Hyper AI Config')}</h2>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>{t('hyperAi.onboarding.provider', 'AI Provider')}</Label>
            <Select value={selectedProvider} onValueChange={(v) => { setSelectedProvider(v); setModelInput('') }}>
              <SelectTrigger>
                <SelectValue placeholder={t('hyperAi.onboarding.selectProvider', 'Select provider')} />
              </SelectTrigger>
              <SelectContent>
                {providers.map(p => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {selectedProvider === 'custom' && (
            <div className="space-y-2">
              <Label>{t('hyperAi.onboarding.baseUrl', 'Base URL')}</Label>
              <Input
                value={customBaseUrl}
                onChange={e => setCustomBaseUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
              />
            </div>
          )}

          <div className="space-y-2">
            <Label>{t('hyperAi.onboarding.apiKey', 'API Key')}</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder={currentProfile?.llm_configured ? t('hyperAi.onboarding.apiKeyConfigured', 'Enter new API key to update') : 'sk-...'}
            />
          </div>

          {selectedProvider && (
            <div className="space-y-2">
              <Label>{t('hyperAi.onboarding.model', 'Model')}</Label>
              <div className="flex gap-1">
                <Input
                  value={modelInput}
                  onChange={e => setModelInput(e.target.value)}
                  placeholder={t('hyperAi.onboarding.modelPlaceholder', 'Enter or select model')}
                  className="flex-1"
                />
                {currentProvider && currentProvider.models.length > 0 && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" size="icon" className="shrink-0">
                        <ChevronDown className="w-4 h-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="max-h-60 overflow-y-auto">
                      {currentProvider.models.map(m => (
                        <DropdownMenuItem key={m} onClick={() => setModelInput(m)}>
                          {m}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="flex items-center gap-2 text-destructive text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span className="break-all">{error}</span>
          </div>
        )}

        {success && (
          <div className="flex items-center gap-2 text-green-600 text-sm">
            <CheckCircle2 className="w-4 h-4" />
            {t('hyperAi.onboarding.connectionSuccess', 'Connection successful!')}
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <Button variant="outline" onClick={onClose} className="flex-1">
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleSave} disabled={!selectedProvider || !apiKey || saving} className="flex-1">
            {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
            {saving ? t('hyperAi.onboarding.testing', 'Testing...') : t('common.save', 'Save')}
          </Button>
        </div>
      </div>
    </div>
  )
}

// Welcome message component
export function BotConvIcon() {
  return (
    <svg viewBox="0 0 1024 1024" className="w-4 h-4 flex-shrink-0" fill="currentColor">
      <path d="M0 0m128 0l768 0q128 0 128 128l0 768q0 128-128 128l-768 0q-128 0-128-128l0-768q0-128 128-128Z" fill="#E1EBFF"/>
      <path d="M640.704 213.12A75.136 75.136 0 0 0 588.544 192c-18.944 0-37.44 7.552-50.688 21.12a89.536 89.536 0 0 0-20.032 72.32v14.336A97.152 97.152 0 0 1 479.616 364.8c-26.88 26.048-61.632 43.52-98.688 48.384-6.4 0-17.728-2.304-19.648-2.304a124.672 124.672 0 0 0-140.672 46.528 33.088 33.088 0 0 0 4.544 39.68L328.384 600.32l-131.584 182.272a32.192 32.192 0 0 0 10.944 44.608c10.624 6.4 23.488 6.4 34.048 0l179.968-133.504 104.768 104.768a32 32 0 0 0 38.592 4.928 127.168 127.168 0 0 0 46.848-143.68v-5.312l-3.392-11.712c1.92-32.896 16.256-63.936 39.68-86.976a122.24 122.24 0 0 1 77.184-50.304h14.72c25.344 3.84 51.072-3.392 70.72-19.648a71.424 71.424 0 0 0 4.928-96L640.64 213.12z" fill="#3478FF"/>
    </svg>
  )
}

export function TelegramSmallIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-[#26A5E4]" fill="currentColor">
      <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
    </svg>
  )
}

export function DiscordSmallIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-[#5865F2]" fill="currentColor">
      <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.947 2.418-2.157 2.418z"/>
    </svg>
  )
}

export function NotificationBellSmallIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 1024 1024" fill="currentColor">
      <path d="M512 0c282.666667 0 512 229.333333 512 512S794.666667 1024 512 1024 0 794.666667 0 512 229.333333 0 512 0z" fill="#2E74EE" opacity=".12" />
      <path d="M505.6 771.2L309.333333 611.2h-29.866666c-19.2 0-34.133333-14.933333-34.133334-34.133333V442.666667c0-19.2 14.933333-33.066667 34.133334-33.066667h36.266666l188.8-155.733333s48-30.933333 48 26.666666v462.933334c0 36.266667-20.266667 38.4-34.133333 34.133333-8.533333-2.133333-12.8-6.4-12.8-6.4z m117.333333-160c-6.4 0-12.8-2.133333-17.066666-7.466667-8.533333-9.6-7.466667-24.533333 2.133333-32 17.066667-14.933333 26.666667-36.266667 26.666667-58.666666s-9.6-43.733333-25.6-58.666667c-9.6-8.533333-9.6-23.466667-2.133334-32 8.533333-9.6 22.4-10.666667 32-2.133333 25.6 23.466667 40.533333 57.6 40.533334 92.8 0 35.2-14.933333 69.333333-41.6 92.8-4.266667 3.2-9.6 5.333333-14.933334 5.333333z m21.333334 88.533333c-8.533333 0-17.066667-5.333333-21.333334-13.866666-4.266667-11.733333 1.066667-24.533333 12.8-28.8 58.666667-23.466667 97.066667-77.866667 97.066667-139.733334s-38.4-116.266667-98.133333-139.733333c-11.733333-4.266667-17.066667-18.133333-12.8-28.8s18.133333-17.066667 29.866666-12.8c37.333333 14.933333 68.266667 39.466667 90.666667 70.4 23.466667 33.066667 35.2 70.4 35.2 110.933333 0 39.466667-11.733333 77.866667-35.2 109.866667-22.4 32-53.333333 56.533333-90.666667 70.4-2.133333 1.066667-4.266667 2.133333-7.466666 2.133333z" fill="#2E74EE" />
    </svg>
  )
}

export function WelcomeMessage({
  nickname,
  t,
  onSuggestionClick
}: {
  nickname?: string
  t: any
  onSuggestionClick: (question: string) => void
}) {
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [isNewUser, setIsNewUser] = useState(true)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/hyper-ai/suggestions')
      .then(res => res.json())
      .then(data => {
        setSuggestions(data.suggestions || [])
        setIsNewUser(data.is_new_user ?? true)
      })
      .catch(() => {
        setSuggestions([])
        setIsNewUser(true)
      })
      .finally(() => setLoading(false))
  }, [])

  const greeting = nickname
    ? t('hyperAi.welcomeWithName', { name: nickname, defaultValue: `你好，${nickname}！我是 Hyper AI，你的专属交易助手。` })
    : t('hyperAi.welcomeNoName', '你好！我是 Hyper AI，Hyper Alpha Arena 的智能助手。')

  // Default suggestions for new users (follows i18n)
  const defaultSuggestions = [
    t('hyperAi.defaultSuggestions.intro', 'What can you help me with?'),
    t('hyperAi.defaultSuggestions.setup', 'Guide me through the initial setup'),
    t('hyperAi.defaultSuggestions.first', 'I want to create my first trading strategy'),
    t('hyperAi.defaultSuggestions.strategyRadar', 'Help me find strategy ideas from Strategy Radar'),
    t('hyperAi.defaultSuggestions.walletSignals', 'How do I connect Hyper Insight wallet signals?'),
  ]

  const displaySuggestions = (isNewUser || suggestions.length === 0) ? defaultSuggestions : suggestions

  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
        <Bot className="w-8 h-8 text-primary" />
      </div>
      <p className="text-lg mb-4">{greeting}</p>
      <div className="text-sm text-muted-foreground space-y-1 max-w-md">
        <p>{t('hyperAi.welcomeCapabilities', '我可以帮你：')}</p>
        <ul className="text-left list-disc list-inside space-y-1 mt-2">
          <li>{t('hyperAi.capability1', '了解系统功能和使用方法')}</li>
          <li>{t('hyperAi.capability2', '生成和优化 AI 交易策略')}</li>
          <li>{t('hyperAi.capability3', '管理 AI 交易员和钱包配置')}</li>
          <li>{t('hyperAi.capability4', '分析市场数据和交易表现')}</li>
        </ul>
        <p className="mt-4">{t('hyperAi.welcomePrompt', '有什么想了解的，直接问我就行。')}</p>
      </div>

      {/* Suggestion buttons */}
      {!loading && displaySuggestions.length > 0 && (
        <div className="mt-6 space-y-2 w-full max-w-md">
          {displaySuggestions.map((question, idx) => (
            <button
              key={idx}
              onClick={() => onSuggestionClick(question)}
              className="w-full px-4 py-3 text-left text-sm rounded-lg border border-border bg-card hover:bg-accent hover:border-primary/50 transition-colors"
            >
              {question}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
