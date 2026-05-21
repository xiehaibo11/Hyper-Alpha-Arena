import { useEffect, useState } from 'react'
import type { TFunction } from 'i18next'
import {
  Archive,
  ArchiveRestore,
  MessageSquare,
  PanelLeftClose,
  Plus,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { Conversation } from './HyperAiChatTypes'
import {
  BotConvIcon,
  DiscordSmallIcon,
  TelegramSmallIcon,
} from './HyperAiPageSupport'

interface BotConfig {
  platform: string
  bot_username: string | null
  status: string
  bot_app_id?: string
}

interface Props {
  collapsed: boolean
  currentConvId: number | null
  refreshKey: number
  t: TFunction
  onCollapse: () => void
  onNewConversation: () => void
  onSelectConversation: (id: number, archived: boolean) => void
  onArchivedCurrent: () => void
}

export default function HyperAiConversationSidebar({
  collapsed,
  currentConvId,
  refreshKey,
  t,
  onCollapse,
  onNewConversation,
  onSelectConversation,
  onArchivedCurrent,
}: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [pendingArchiveId, setPendingArchiveId] = useState<number | null>(null)
  const [loadingId, setLoadingId] = useState<number | null>(null)
  const [botConfig, setBotConfig] = useState<BotConfig | null>(null)
  const [discordBotConfig, setDiscordBotConfig] = useState<BotConfig | null>(null)

  useEffect(() => {
    void fetchConversations()
  }, [showArchived, refreshKey])

  useEffect(() => {
    void fetchBotConfig()
    void fetchDiscordBotConfig()
  }, [])

  const fetchConversations = async () => {
    try {
      const res = await fetch(`/api/hyper-ai/conversations?archived=${showArchived}`)
      const data = await res.json()
      setConversations(data.conversations || [])
    } catch (e) {
      console.error('Failed to fetch conversations:', e)
      setConversations([])
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

  const archiveConversation = async (conversationId: number) => {
    setLoadingId(conversationId)
    try {
      const res = await fetch(`/api/hyper-ai/conversations/${conversationId}/archive`, { method: 'POST' })
      if (!res.ok) throw new Error(`Archive failed: ${res.status}`)
      setPendingArchiveId(null)
      if (currentConvId === conversationId) onArchivedCurrent()
      await fetchConversations()
    } catch (e) {
      console.error('Failed to archive conversation:', e)
    } finally {
      setLoadingId(null)
    }
  }

  const restoreConversation = async (conversationId: number) => {
    setLoadingId(conversationId)
    try {
      const res = await fetch(`/api/hyper-ai/conversations/${conversationId}/unarchive`, { method: 'POST' })
      if (!res.ok) throw new Error(`Restore failed: ${res.status}`)
      setShowArchived(false)
      onSelectConversation(conversationId, false)
    } catch (e) {
      console.error('Failed to restore conversation:', e)
    } finally {
      setLoadingId(null)
    }
  }

  if (collapsed) return null

  return (
    <div className="w-64 border-r flex flex-col transition-all duration-200">
      <div className="p-3 flex items-center gap-2">
        {showArchived ? (
          <Button
            variant="outline"
            onClick={() => setShowArchived(false)}
            className="flex-1"
            size="sm"
          >
            <MessageSquare className="w-4 h-4 mr-2" />
            {t('hyperAi.activeChats', 'Active Chats')}
          </Button>
        ) : (
          <Button onClick={onNewConversation} className="flex-1" size="sm">
            <Plus className="w-4 h-4 mr-2" />
            {t('hyperAi.newChat', 'New Chat')}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="px-2 shrink-0"
          onClick={() => {
            setShowArchived(value => !value)
            setPendingArchiveId(null)
          }}
          title={showArchived ? t('hyperAi.activeChats', 'Active Chats') : t('hyperAi.archivedChats', 'Archived Chats')}
        >
          {showArchived ? <ArchiveRestore className="w-4 h-4" /> : <Archive className="w-4 h-4" />}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="px-2 shrink-0"
          onClick={onCollapse}
          title={t('hyperAi.collapseSidebar', 'Collapse sidebar')}
        >
          <PanelLeftClose className="w-4 h-4" />
        </Button>
      </div>
      {showArchived && (
        <div className="px-4 pb-2 text-xs font-medium text-muted-foreground">
          {t('hyperAi.archivedChats', 'Archived Chats')}
        </div>
      )}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {conversations.map(conv => (
            <ConversationRow
              key={conv.id}
              conversation={conv}
              current={currentConvId === conv.id}
              showArchived={showArchived}
              pendingArchive={pendingArchiveId === conv.id}
              loading={loadingId === conv.id}
              botConnected={botConfig?.status === 'connected'}
              discordConnected={discordBotConfig?.status === 'connected'}
              t={t}
              onSelect={() => onSelectConversation(conv.id, Boolean(conv.is_archived))}
              onAskArchive={() => setPendingArchiveId(conv.id)}
              onCancelArchive={() => setPendingArchiveId(null)}
              onArchive={() => archiveConversation(conv.id)}
              onRestore={() => restoreConversation(conv.id)}
            />
          ))}
          {conversations.length === 0 && (
            <div className="px-3 py-8 text-center text-xs text-muted-foreground">
              {showArchived
                ? t('hyperAi.noArchivedChats', 'No archived chats')
                : t('hyperAi.noChats', 'No chats yet')}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}

function ConversationRow({
  conversation,
  current,
  showArchived,
  pendingArchive,
  loading,
  botConnected,
  discordConnected,
  t,
  onSelect,
  onAskArchive,
  onCancelArchive,
  onArchive,
  onRestore,
}: {
  conversation: Conversation
  current: boolean
  showArchived: boolean
  pendingArchive: boolean
  loading: boolean
  botConnected: boolean
  discordConnected: boolean
  t: TFunction
  onSelect: () => void
  onAskArchive: () => void
  onCancelArchive: () => void
  onArchive: () => void
  onRestore: () => void
}) {
  return (
    <div className={`group rounded-lg transition-colors ${current ? 'bg-secondary text-secondary-foreground' : 'hover:bg-muted text-muted-foreground'} ${conversation.is_bot_conversation ? 'border border-blue-500/30 bg-blue-500/5' : ''}`}>
      <button onClick={onSelect} className="w-full text-left px-3 pt-2.5 pb-1.5 text-sm">
        {conversation.is_bot_conversation ? (
          <>
            <div className="flex items-center gap-2">
              <BotConvIcon />
              <span className="truncate font-medium">{conversation.title}</span>
            </div>
            <div className="flex items-center gap-1.5 mt-1.5 ml-6">
              {botConnected && <TelegramSmallIcon />}
              {discordConnected && <DiscordSmallIcon />}
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <MessageSquare className="w-4 h-4 flex-shrink-0" />
              <span className="truncate">{conversation.title}</span>
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {conversation.message_count} {t('hyperAi.messages', 'messages')}
            </div>
          </>
        )}
      </button>
      <div className="flex items-center justify-end gap-1 px-2 pb-2">
        {showArchived ? (
          <button
            onClick={onRestore}
            disabled={loading}
            className="rounded px-2 py-1 text-[11px] text-primary hover:bg-primary/10 disabled:opacity-50"
            title={t('hyperAi.restoreChat', 'Restore chat')}
          >
            <ArchiveRestore className="h-3.5 w-3.5" />
          </button>
        ) : pendingArchive ? (
          <>
            <button
              onClick={onCancelArchive}
              className="rounded px-2 py-1 text-[11px] hover:bg-muted"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              onClick={onArchive}
              disabled={loading}
              className="rounded px-2 py-1 text-[11px] font-medium text-red-500 hover:bg-red-500/10 disabled:opacity-50"
            >
              {t('common.confirm', 'Confirm')}
            </button>
          </>
        ) : (
          <button
            onClick={onAskArchive}
            className="rounded px-2 py-1 text-[11px] opacity-70 hover:bg-muted group-hover:opacity-100"
            title={t('hyperAi.archiveChat', 'Archive chat')}
          >
            <Archive className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}
