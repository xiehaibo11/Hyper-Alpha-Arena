import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { TFunction } from 'i18next'
import {
  Blocks,
  Brain,
  ChevronRight,
  Pencil,
  Search,
  Settings,
  Wrench,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import BotIntegrationModal from './BotIntegrationModal'
import NotificationConfigModal from './NotificationConfigModal'
import ToolConfigModal, { type ToolInfo } from './ToolConfigModal'
import {
  DiscordSmallIcon,
  LLMConfigModal,
  MemoryModal,
  NotificationBellSmallIcon,
  TelegramSmallIcon,
} from './HyperAiPageSupport'
import type { LLMProvider, SkillInfo } from './HyperAiPageSupport'

interface BotConfig {
  platform: string
  bot_username: string | null
  status: string
  bot_app_id?: string
}

interface Props {
  activeSkill: string | null
  currentLang: 'zh' | 'en'
  t: TFunction
}

export default function HyperAiConfigPanel({ activeSkill, currentLang, t }: Props) {
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [profile, setProfile] = useState<any>(null)
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [skillsLoading, setSkillsLoading] = useState(false)
  const [skillsEditMode, setSkillsEditMode] = useState(false)
  const [pendingSkillToggles, setPendingSkillToggles] = useState<Record<string, boolean>>({})
  const [botConfig, setBotConfig] = useState<BotConfig | null>(null)
  const [discordBotConfig, setDiscordBotConfig] = useState<BotConfig | null>(null)
  const [notificationCount, setNotificationCount] = useState(0)
  const [externalTools, setExternalTools] = useState<ToolInfo[]>([])
  const [showConfigModal, setShowConfigModal] = useState(false)
  const [showMemoryModal, setShowMemoryModal] = useState(false)
  const [showBotModal, setShowBotModal] = useState(false)
  const [showDiscordBotModal, setShowDiscordBotModal] = useState(false)
  const [showNotificationModal, setShowNotificationModal] = useState(false)
  const [showToolModal, setShowToolModal] = useState(false)
  const [selectedTool, setSelectedTool] = useState<ToolInfo | null>(null)

  useEffect(() => {
    void fetchProviders()
    void fetchProfile()
    void fetchSkills()
    void fetchBotConfig()
    void fetchDiscordBotConfig()
    void fetchNotificationConfig()
    void fetchExternalTools()
  }, [])

  const fetchProviders = async () => {
    try {
      const res = await fetch('/api/hyper-ai/providers')
      const data = await res.json()
      setProviders(data.providers || [])
    } catch (e) {
      console.error('Failed to fetch providers:', e)
    }
  }

  const fetchProfile = async () => {
    try {
      const res = await fetch('/api/hyper-ai/profile')
      const data = await res.json()
      setProfile(data)
    } catch (e) {
      console.error('Failed to fetch profile:', e)
    }
  }

  const fetchSkills = async () => {
    try {
      const res = await fetch('/api/hyper-ai/skills')
      const data = await res.json()
      setSkills(data.skills || [])
    } catch (e) {
      console.error('Failed to fetch skills:', e)
    }
  }

  const fetchExternalTools = async () => {
    try {
      const res = await fetch('/api/hyper-ai/tools')
      const data = await res.json()
      setExternalTools(data.tools || [])
    } catch (e) {
      console.error('Failed to fetch external tools:', e)
    }
  }

  const fetchBotConfig = async () => {
    try {
      const res = await fetch('/api/bot/config/telegram')
      const data = await res.json()
      setBotConfig(data.config || null)
    } catch (e) {
      console.error('Failed to fetch bot config:', e)
    }
  }

  const fetchDiscordBotConfig = async () => {
    try {
      const res = await fetch('/api/bot/config/discord')
      const data = await res.json()
      setDiscordBotConfig(data.config || null)
    } catch (e) {
      console.error('Failed to fetch discord bot config:', e)
    }
  }

  const fetchNotificationConfig = async () => {
    try {
      const res = await fetch('/api/bot/notification-config')
      const data = await res.json()
      const cfg = data.config || { ai_trader: true, program_trader: true, signal_pools: {} }
      let count = 0
      if (cfg.ai_trader) count++
      if (cfg.program_trader) count++
      count += Object.values(cfg.signal_pools as Record<string, boolean>).filter(Boolean).length
      setNotificationCount(count)
    } catch (e) {
      console.error('Failed to fetch notification config:', e)
    }
  }

  const handleSkillsEditSave = async () => {
    setSkillsLoading(true)
    try {
      for (const [name, enabled] of Object.entries(pendingSkillToggles)) {
        await fetch(`/api/hyper-ai/skills/${name}/toggle`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled })
        })
      }
      setSkills(prev => prev.map(s => (
        pendingSkillToggles[s.name] === undefined ? s : { ...s, enabled: pendingSkillToggles[s.name] }
      )))
    } catch (e) {
      console.error('Failed to save skill toggles:', e)
    } finally {
      setSkillsLoading(false)
      setSkillsEditMode(false)
      setPendingSkillToggles({})
    }
  }

  return (
    <>
      <div className="w-[500px] border-l p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium flex items-center gap-1.5">
            <Settings className="w-4 h-4 shrink-0" />
            {t('hyperAi.configTitle', 'Hyper AI Config')}
          </h3>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setShowConfigModal(true)}>
            <Pencil className="w-3.5 h-3.5" />
          </Button>
        </div>

        {profile && (
          <div
            className="space-y-1.5 text-sm cursor-pointer hover:bg-muted/50 rounded-lg p-2 -mx-2 transition-colors"
            onClick={() => setShowConfigModal(true)}
          >
            <InfoRow label="Provider" value={profile.llm_provider || 'Not configured'} />
            <InfoRow label="Model" value={profile.llm_model || '-'} />
            {profile.llm_base_url && <InfoRow label="Base URL" value={profile.llm_base_url} />}
          </div>
        )}

        <button
          onClick={() => setShowMemoryModal(true)}
          className="w-full flex items-center gap-1.5 pt-4 py-1 rounded-lg text-sm hover:bg-muted/50 transition-colors text-left"
        >
          <Brain className="w-4 h-4 text-primary shrink-0" />
          <span className="text-sm font-medium">{t('hyperAi.memory.button', 'Memory')}</span>
          <ChevronRight className="w-3 h-3 text-muted-foreground ml-auto shrink-0" />
        </button>

        <SkillSection
          skills={skills}
          activeSkill={activeSkill}
          editMode={skillsEditMode}
          loading={skillsLoading}
          pending={pendingSkillToggles}
          t={t}
          onEdit={() => setSkillsEditMode(true)}
          onCancel={() => {
            setSkillsEditMode(false)
            setPendingSkillToggles({})
          }}
          onSave={handleSkillsEditSave}
          onToggle={(name, enabled) => setPendingSkillToggles(prev => ({ ...prev, [name]: enabled }))}
        />

        {externalTools.length > 0 && (
          <div className="pt-4">
            <h4 className="text-sm font-medium flex items-center gap-1.5 mb-2">
              <Wrench className="w-4 h-4 shrink-0" />
              {t('hyperAi.tools', 'Tools')}
            </h4>
            <div className="space-y-1">
              {externalTools.map(tool => (
                <button
                  key={tool.name}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors text-left"
                  onClick={() => { setSelectedTool(tool); setShowToolModal(true) }}
                >
                  <Search className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                  <span className="text-xs truncate flex-1">
                    {currentLang === 'zh' ? tool.display_name_zh : tool.display_name}
                  </span>
                  {tool.configured ? (
                    <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                  ) : (
                    <span className="text-[10px] text-primary shrink-0">{t('tools.setup', 'Setup')}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        <IntegrationSection
          botConfig={botConfig}
          discordBotConfig={discordBotConfig}
          notificationCount={notificationCount}
          t={t}
          onTelegram={() => setShowBotModal(true)}
          onDiscord={() => setShowDiscordBotModal(true)}
          onNotifications={() => setShowNotificationModal(true)}
        />
      </div>

      <LLMConfigModal open={showConfigModal} onClose={() => setShowConfigModal(false)} providers={providers} currentProfile={profile} onSaved={fetchProfile} />
      <MemoryModal open={showMemoryModal} onClose={() => setShowMemoryModal(false)} />
      <BotIntegrationModal open={showBotModal} onClose={() => setShowBotModal(false)} platform="telegram" onConnected={fetchBotConfig} currentBotUsername={botConfig?.status === 'connected' ? botConfig.bot_username : undefined} />
      <BotIntegrationModal open={showDiscordBotModal} onClose={() => setShowDiscordBotModal(false)} platform="discord" onConnected={fetchDiscordBotConfig} currentBotUsername={discordBotConfig?.status === 'connected' ? discordBotConfig.bot_username : undefined} currentBotAppId={discordBotConfig?.bot_app_id} />
      <NotificationConfigModal open={showNotificationModal} onClose={() => setShowNotificationModal(false)} onConfigChange={setNotificationCount} />
      <ToolConfigModal open={showToolModal} onClose={() => { setShowToolModal(false); setSelectedTool(null) }} tool={selectedTool} onSaved={fetchExternalTools} />
    </>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center">
      <span className="text-muted-foreground shrink-0 w-[72px]">{label}</span>
      <span className="truncate">{value}</span>
    </div>
  )
}

function SkillSection({
  skills,
  activeSkill,
  editMode,
  loading,
  pending,
  t,
  onEdit,
  onCancel,
  onSave,
  onToggle,
}: {
  skills: SkillInfo[]
  activeSkill: string | null
  editMode: boolean
  loading: boolean
  pending: Record<string, boolean>
  t: TFunction
  onEdit: () => void
  onCancel: () => void
  onSave: () => void
  onToggle: (name: string, enabled: boolean) => void
}) {
  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-medium flex items-center gap-1.5">
          <Blocks className="w-4 h-4 shrink-0" />
          {t('hyperAi.skills', 'Skills')}
        </h4>
        {skills.length > 0 && !editMode && (
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onEdit}>
            <Pencil className="w-3.5 h-3.5" />
          </Button>
        )}
      </div>
      <p className="text-[10px] text-muted-foreground/60 mb-2 px-0.5">
        {t('hyperAi.skillsHint', 'Auto-loaded by AI, or type /command')}
      </p>
      {skills.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t('hyperAi.skillsLoading', 'Loading...')}</p>
      ) : (
        <div className="space-y-1">
          {skills.map(skill => {
            const enabled = pending[skill.name] === undefined ? skill.enabled : pending[skill.name]
            return (
              <div key={skill.name} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-muted/50 transition-colors">
                {editMode ? (
                  <Switch checked={enabled} onCheckedChange={v => onToggle(skill.name, v)} disabled={loading} className="scale-75 origin-left shrink-0" />
                ) : (
                  <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${activeSkill === skill.name ? 'bg-red-500' : enabled ? 'bg-green-500' : 'bg-muted-foreground/30'}`} />
                )}
                <span className="text-xs truncate flex-1">{t(`hyperAi.skillNames.${skill.name}`, skill.name)}</span>
                <span className="text-[10px] text-muted-foreground/50 shrink-0 font-mono">{skill.command}</span>
              </div>
            )
          })}
          {editMode && (
            <div className="flex gap-2 pt-2">
              <Button variant="outline" size="sm" onClick={onCancel} className="h-7 px-3 text-xs">{t('hyperAi.skillsCancel', 'Cancel')}</Button>
              <Button size="sm" onClick={onSave} disabled={loading} className="h-7 px-3 text-xs">{t('hyperAi.skillsSave', 'Save')}</Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function IntegrationSection({
  botConfig,
  discordBotConfig,
  notificationCount,
  t,
  onTelegram,
  onDiscord,
  onNotifications,
}: {
  botConfig: BotConfig | null
  discordBotConfig: BotConfig | null
  notificationCount: number
  t: TFunction
  onTelegram: () => void
  onDiscord: () => void
  onNotifications: () => void
}) {
  return (
    <div className="pt-4">
      <h4 className="text-sm font-medium flex items-center gap-1.5 mb-2">
        <Blocks className="w-4 h-4 shrink-0" />
        {t('hyperAi.integrations', 'Integrations')}
        <button onClick={onNotifications} className="ml-auto flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-primary/10 hover:bg-primary/20 transition-colors" title={t('bot.notificationSettings', 'Push Notifications')}>
          <NotificationBellSmallIcon />
          {notificationCount > 0 && <span className="text-[10px] text-primary font-medium min-w-[14px] text-center">{notificationCount}</span>}
        </button>
      </h4>
      <div className="space-y-2">
        <IntegrationRow icon={<TelegramSmallIcon />} label={t('hyperAi.telegramBot', 'Telegram Bot')} connectedLabel={botConfig?.bot_username || ''} connected={botConfig?.status === 'connected'} onClick={onTelegram} t={t} />
        <IntegrationRow icon={<DiscordSmallIcon />} label={t('hyperAi.discordBot', 'Discord Bot')} connectedLabel={discordBotConfig?.bot_username || ''} connected={discordBotConfig?.status === 'connected'} onClick={onDiscord} t={t} />
      </div>
    </div>
  )
}

function IntegrationRow({ icon, label, connected, connectedLabel, onClick, t }: {
  icon: ReactNode
  label: string
  connected: boolean
  connectedLabel: string
  onClick: () => void
  t: TFunction
}) {
  return (
    <button className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors text-left" onClick={onClick}>
      {icon}
      <span className="text-xs">{label}</span>
      {connected ? (
        <>
          <span className="ml-auto text-[10px] text-muted-foreground">@{connectedLabel}</span>
          <span className="w-2 h-2 rounded-full bg-green-500" />
        </>
      ) : (
        <span className="ml-auto text-[10px] text-primary">{t('bot.setup', 'Setup')}</span>
      )}
    </button>
  )
}
