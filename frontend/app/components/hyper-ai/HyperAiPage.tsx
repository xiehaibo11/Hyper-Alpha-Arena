/**
 * HyperAiPage - Independent page for Hyper AI (three-column layout)
 * Left: Conversation list
 * Center: Chat area
 * Right: Config panel
 */
import { useState, useEffect, useRef } from 'react'
import type { ClipboardEvent, DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Switch } from '@/components/ui/switch'
import {
  Plus,
  Send,
  Settings,
  MessageSquare,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Loader2,
  Pencil,
  X,
  Wrench,
  Brain,
  Blocks,
  Search as SearchIcon,
  ImagePlus
} from 'lucide-react'
import { pollAiStream } from '@/lib/pollAiStream'
import BotIntegrationModal from './BotIntegrationModal'
import NotificationConfigModal from './NotificationConfigModal'
import ToolConfigModal, { type ToolInfo } from './ToolConfigModal'
import MessageBubble from './MessageBubble'
import type {
  ChatImageAttachment,
  Conversation,
  Message,
  ToolCallEntry,
  ToolCallLogEntry,
} from './HyperAiChatTypes'

import {
  BotConvIcon,
  DiscordSmallIcon,
  LLMConfigModal,
  MAX_IMAGE_ATTACHMENTS,
  MAX_IMAGE_BYTES,
  MemoryModal,
  NotificationBellSmallIcon,
  TelegramSmallIcon,
  WelcomeMessage,
  readImageAttachment,
} from './HyperAiPageSupport'
import type {
  CompressionPoint,
  LLMProvider,
  SkillInfo,
  TokenUsage,
} from './HyperAiPageSupport'

export default function HyperAiPage() {
  const { t, i18n } = useTranslation()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConvId, setCurrentConvId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [compressionPoints, setCompressionPoints] = useState<CompressionPoint[]>([])
  const [tokenUsage, setTokenUsage] = useState<TokenUsage | null>(null)
  const [inputValue, setInputValue] = useState('')
  const [imageAttachments, setImageAttachments] = useState<ChatImageAttachment[]>([])
  const [sending, setSending] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [profile, setProfile] = useState<any>(null)
  const [nickname, setNickname] = useState<string>('')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [showConfig, setShowConfig] = useState(true)
  const [showConfigModal, setShowConfigModal] = useState(false)
  const [showMemoryModal, setShowMemoryModal] = useState(false)
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [activeSkill, setActiveSkill] = useState<string | null>(null)
  const [skillsLoading, setSkillsLoading] = useState(false)
  const [skillsEditMode, setSkillsEditMode] = useState(false)
  const [pendingSkillToggles, setPendingSkillToggles] = useState<Record<string, boolean>>({})
  const [showBotModal, setShowBotModal] = useState(false)
  const [showDiscordBotModal, setShowDiscordBotModal] = useState(false)
  const [botConfig, setBotConfig] = useState<{ platform: string; bot_username: string | null; status: string } | null>(null)
  const [discordBotConfig, setDiscordBotConfig] = useState<{ platform: string; bot_username: string | null; bot_app_id?: string; status: string } | null>(null)
  const [showNotificationModal, setShowNotificationModal] = useState(false)
  const [notificationCount, setNotificationCount] = useState(0)
  const [externalTools, setExternalTools] = useState<ToolInfo[]>([])
  const [showToolModal, setShowToolModal] = useState(false)
  const [selectedTool, setSelectedTool] = useState<ToolInfo | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Get current language
  const currentLang = i18n.language?.startsWith('zh') ? 'zh' : 'en'

  useEffect(() => {
    fetchConversations()
    fetchProviders()
    fetchProfile()
    fetchSkills()
    fetchBotConfig()
    fetchDiscordBotConfig()
    fetchNotificationConfig()
    fetchExternalTools()
  }, [])

  useEffect(() => {
    // Don't fetch messages while sending - it would overwrite the streaming message
    if (currentConvId && !sending) {
      fetchMessages(currentConvId)
    }
  }, [currentConvId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  // Check for pending prompt from other pages (e.g. Factor Analysis "Ask AI")
  useEffect(() => {
    const pending = localStorage.getItem('hyper-ai-pending-prompt')
    if (pending) {
      localStorage.removeItem('hyper-ai-pending-prompt')
      setInputValue(pending)
      // Focus the textarea after a brief delay
      setTimeout(() => textareaRef.current?.focus(), 200)
    }
  }, [])

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

  const fetchExternalTools = async () => {
    try {
      const res = await fetch('/api/hyper-ai/tools')
      const data = await res.json()
      setExternalTools(data.tools || [])
    } catch (e) {
      console.error('Failed to fetch external tools:', e)
    }
  }

  const fetchConversations = async () => {
    try {
      const res = await fetch('/api/hyper-ai/conversations')
      const data = await res.json()
      setConversations(data.conversations || [])
    } catch (e) {
      console.error('Failed to fetch conversations:', e)
    }
  }

  const fetchMessages = async (convId: number) => {
    try {
      const res = await fetch(`/api/hyper-ai/conversations/${convId}/messages`)
      const data = await res.json()
      setMessages(data.messages || [])
      setCompressionPoints(data.compression_points || [])
      setTokenUsage(data.token_usage || null)
    } catch (e) {
      console.error('Failed to fetch messages:', e)
    }
  }

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
      if (data.nickname) {
        setNickname(data.nickname)
      }
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

  const toggleSkill = async (skillName: string, enabled: boolean) => {
    setSkillsLoading(true)
    try {
      await fetch(`/api/hyper-ai/skills/${skillName}/toggle`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
      })
      setSkills(prev => prev.map(s =>
        s.name === skillName ? { ...s, enabled } : s
      ))
    } catch (e) {
      console.error('Failed to toggle skill:', e)
    } finally {
      setSkillsLoading(false)
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
      setSkills(prev => prev.map(s =>
        pendingSkillToggles[s.name] !== undefined
          ? { ...s, enabled: pendingSkillToggles[s.name] }
          : s
      ))
    } catch (e) {
      console.error('Failed to save skill toggles:', e)
    } finally {
      setSkillsLoading(false)
      setSkillsEditMode(false)
      setPendingSkillToggles({})
    }
  }

  const handleSkillsEditCancel = () => {
    setSkillsEditMode(false)
    setPendingSkillToggles({})
  }

  const addImageFiles = async (files: File[] | FileList) => {
    const candidates = Array.from(files).filter(file =>
      file.type.startsWith('image/') && file.size > 0 && file.size <= MAX_IMAGE_BYTES
    )
    if (!candidates.length) return

    try {
      const prepared = await Promise.all(
        candidates.slice(0, MAX_IMAGE_ATTACHMENTS).map(file => readImageAttachment(file))
      )
      setImageAttachments(prev => [...prev, ...prepared].slice(0, MAX_IMAGE_ATTACHMENTS))
    } catch (e) {
      console.error('Failed to attach image:', e)
    }
  }

  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.items || [])
      .filter(item => item.kind === 'file')
      .map(item => item.getAsFile())
      .filter((file): file is File => !!file && file.type.startsWith('image/'))
    if (files.length) {
      void addImageFiles(files)
    }
  }

  const handleDrop = (e: DragEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.dataTransfer.files || []).filter(file => file.type.startsWith('image/'))
    if (!files.length) return
    e.preventDefault()
    void addImageFiles(files)
  }

  const removeImageAttachment = (id: string) => {
    setImageAttachments(prev => prev.filter(item => item.id !== id))
  }

  const handleNewConversation = () => {
    // Lazy creation: just clear current state, don't create in DB yet
    setCurrentConvId(null)
    setMessages([])
    setCompressionPoints([])
    setTokenUsage(null)
    setActiveSkill(null)
    setImageAttachments([])
  }

  const handleSend = async () => {
    if ((!inputValue.trim() && imageAttachments.length === 0) || sending) return

    const pendingImages = imageAttachments
    const userMessage = inputValue.trim() || (currentLang === 'zh' ? '请分析这张图片。' : 'Please analyze the attached image.')
    setInputValue('')
    setImageAttachments([])
    setSending(true)
    setStreamingContent('')

    // Add user message and placeholder assistant message
    const tempAssistantId = Date.now()
    setMessages(prev => [
      ...prev,
      { role: 'user', content: userMessage, attachments: pendingImages },
      {
        role: 'assistant',
        content: '',
        isStreaming: true,
        statusText: t('hyperAi.connecting', 'Connecting...'),
        toolCalls: []
      }
    ])

    try {
      const res = await fetch('/api/hyper-ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage,
          conversation_id: currentConvId,
          lang: currentLang,
          images: pendingImages.map(({ name, mime_type, data_url, size }) => ({
            name,
            mime_type,
            data_url,
            size,
          }))
        })
      })

      const data = await res.json()
      if (data.task_id) {
        // Poll for streaming response
        pollTaskResponse(data.task_id, data.conversation_id)
        if (!currentConvId) {
          setCurrentConvId(data.conversation_id)
        }
      } else {
        throw new Error('No task_id returned')
      }
    } catch (e) {
      console.error('Failed to send message:', e)
      // Remove placeholder on error
      setMessages(prev => prev.slice(0, -1))
      setImageAttachments(pendingImages)
      setSending(false)
    }
  }

  const handleToolConfirmation = async (taskId: string, confirmationId: string, confirmed: boolean) => {
    const nextStatus = confirmed ? 'confirmed' : 'cancelled'
    setMessages(prev => prev.map(message => ({
      ...message,
      toolCalls: message.toolCalls?.map(entry =>
        entry.type === 'confirmation_required' && entry.confirmationId === confirmationId
          ? { ...entry, status: nextStatus }
          : entry
      )
    })))

    try {
      const res = await fetch('/api/hyper-ai/confirm-tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: taskId,
          confirmation_id: confirmationId,
          confirmed,
        }),
      })
      if (!res.ok) {
        throw new Error(`Confirmation failed: ${res.status}`)
      }
    } catch (e) {
      console.error('Failed to submit tool confirmation:', e)
      setMessages(prev => prev.map(message => ({
        ...message,
        toolCalls: message.toolCalls?.map(entry =>
          entry.type === 'confirmation_required' && entry.confirmationId === confirmationId
            ? { ...entry, status: 'failed' }
            : entry
        )
      })))
    }
  }

  const pollTaskResponse = async (taskId: string, convId: number) => {
    let content = ''
    let reasoning = ''
    let toolCalls: ToolCallEntry[] = []
    let doneToolCallsLog: ToolCallLogEntry[] | null = null
    let doneReasoningSnapshot: string | null = null
    let isInterrupted = false
    let interruptedRound = 0

    // Update currentConvId immediately if not set
    if (!currentConvId && convId) {
      setCurrentConvId(convId)
    }

    try {
      const pollResult = await pollAiStream(taskId, {
        interval: 300,
        onChunk: (chunk) => {
          const eventType = chunk.event_type
          const data = chunk.data

          if (eventType === 'content' && data.text) {
            content += data.text
            setStreamingContent(content)
            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? { ...m, content, statusText: '' }
                : m
            ))
          } else if (eventType === 'reasoning' && data.content) {
            reasoning += data.content
            const reasoningText = data.content as string
            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? {
                    ...m,
                    statusText: `Thinking: ${reasoningText.slice(0, 80)}...`,
                    toolCalls: [...(m.toolCalls || []), { type: 'reasoning', content: reasoningText }],
                  }
                : m
            ))
          } else if (eventType === 'tool_call' && data.name) {
            toolCalls.push({ type: 'tool_call', name: data.name, args: data.args || {} })
            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? {
                    ...m,
                    statusText: `${t('hyperAi.calling', 'Calling')} ${data.name}...`,
                    toolCalls: [...(m.toolCalls || []), { type: 'tool_call', name: data.name, args: data.args }]
                  }
                : m
            ))
          } else if (eventType === 'tool_result' && data.name) {
            toolCalls.push({
              type: 'tool_result',
              name: data.name,
              result: data.result,
              resultStatus: data.status,
              code: data.code,
              durationMs: data.duration_ms,
              parallel: Boolean(data.parallel),
            })
            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? {
                    ...m,
                    statusText: '',
                    toolCalls: [...(m.toolCalls || []), {
                      type: 'tool_result',
                      name: data.name,
                      result: data.result,
                      resultStatus: data.status,
                      code: data.code,
                      durationMs: data.duration_ms,
                      parallel: Boolean(data.parallel),
                    }]
                  }
                : m
            ))
          } else if (eventType === 'skill_loaded' && data.skill_name) {
            setActiveSkill(data.skill_name as string)
          } else if (eventType === 'subagent_progress') {
            const agent = data.subagent || 'Agent'
            let statusMsg = ''
            const progressEntry: any = { type: 'subagent_progress', subagent: agent, step: data.step }

            if (data.step === 'reasoning') {
              statusMsg = `${agent}: ${t('hyperAi.subagentProcessing', 'processing')}...`
              progressEntry.content = data.content || ''
            } else if (data.step === 'tool_call') {
              statusMsg = `${agent}: → ${data.tool || ''}`
              progressEntry.tool = data.tool || ''
            } else if (data.step === 'tool_result') {
              statusMsg = `${agent}: ← ${data.tool || ''}`
              progressEntry.tool = data.tool || ''
            } else if (data.step === 'tool_round') {
              const roundInfo = data.round && data.max_rounds ? ` ${data.round}/${data.max_rounds}` : (data.round ? ` ${data.round}` : '')
              statusMsg = `${agent}: ${t('hyperAi.subagentRound', 'round')}${roundInfo}...`
              progressEntry.round = data.round
              progressEntry.max_rounds = data.max_rounds
            } else {
              statusMsg = `${agent}: ${t('hyperAi.subagentProcessing', 'processing')}...`
            }

            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? { ...m, statusText: statusMsg, toolCalls: [...(m.toolCalls || []), progressEntry] }
                : m
            ))
          } else if (eventType === 'retry') {
            const attempt = data.attempt || 2
            const maxRetries = data.max_retries || 3
            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? { ...m, statusText: `${t('hyperAi.retrying', 'Retrying')} (${attempt}/${maxRetries})...` }
                : m
            ))
          } else if (eventType === 'confirmation_required') {
            const confirmationEntry: ToolCallEntry = {
              type: 'confirmation_required',
              taskId,
              confirmationId: data.confirmation_id,
              name: data.tool_name,
              args: data.args || {},
              description: data.description || '',
              status: 'pending',
            }
            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? {
                    ...m,
                    statusText: t('hyperAi.confirmationRequired', 'Confirmation required'),
                    toolCalls: [...(m.toolCalls || []), confirmationEntry],
                  }
                : m
            ))
            // Force scroll after DOM renders the confirmation card
            setTimeout(() => {
              messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
            }, 100)
          } else if (eventType === 'tool_error') {
            const errorEntry: ToolCallEntry = {
              type: 'tool_error',
              name: data.name,
              message: data.message || data.code || '',
              severity: data.severity || data.status,
            }
            setMessages(prev => prev.map((m, idx) =>
              idx === prev.length - 1 && m.isStreaming
                ? {
                    ...m,
                    statusText: data.message || t('hyperAi.toolWarning', 'Tool warning'),
                    toolCalls: [...(m.toolCalls || []), errorEntry],
                  }
                : m
            ))
          } else if (eventType === 'interrupted') {
            isInterrupted = true
            interruptedRound = data.round || 0
            if (data.conversation_id) {
              setCurrentConvId(data.conversation_id)
            }
          } else if (eventType === 'error') {
            console.error('Stream error:', data.message)
          } else if (eventType === 'done') {
            if (data.content) content = data.content
            if (data.conversation_id) setCurrentConvId(data.conversation_id)
            if (data.token_usage) setTokenUsage(data.token_usage)
            if (data.compression_points) setCompressionPoints(data.compression_points)
            if (data.tool_calls_log) doneToolCallsLog = data.tool_calls_log
            if (data.reasoning_snapshot) doneReasoningSnapshot = data.reasoning_snapshot
          }
        },
        onTaskLost: () => {
          // Task buffer expired — reload conversation to get final result
          if (convId) {
            fetchMessages(convId)
          }
        },
      })

      if (pollResult.status === 'lost') {
        setSending(false)
        return
      }

      // Finalize message - prefer backend done event data, fallback to streaming conversion
      const localToolCallsLog = toolCalls.filter(tc => tc.type === 'tool_call' || tc.type === 'tool_result')
        .reduce((acc: ToolCallLogEntry[], tc) => {
          if (tc.type === 'tool_call' && tc.name) {
            acc.push({ tool: tc.name, args: tc.args || {}, result: '' })
          } else if (tc.type === 'tool_result' && tc.name && acc.length > 0) {
            // Find matching tool call and add result
            const lastCall = acc[acc.length - 1]
            if (lastCall.tool === tc.name) {
              lastCall.result = tc.result || ''
            }
          }
          return acc
        }, [])
      const finalToolCallsLog = doneToolCallsLog || (localToolCallsLog.length > 0 ? localToolCallsLog : null)
      const finalReasoning = doneReasoningSnapshot || reasoning || undefined

      setMessages(prev => prev.map((m, idx) =>
        idx === prev.length - 1 && m.isStreaming
          ? {
              ...m,
              content: content || m.content,
              reasoning_snapshot: finalReasoning,
              tool_calls_log: finalToolCallsLog ? JSON.stringify(finalToolCallsLog) : undefined,
              isStreaming: false,
              statusText: undefined,
              toolCalls: undefined,
              isInterrupted,
              interruptedRound: isInterrupted ? interruptedRound : undefined,
              is_complete: !isInterrupted
            }
          : m
      ))
      setStreamingContent('')
      setSending(false)
      fetchConversations()
    } catch (e) {
      console.error('Polling error:', e)
      setMessages(prev => prev.map((m, idx) =>
        idx === prev.length - 1 && m.isStreaming
          ? { ...m, isStreaming: false, content: content || t('hyperAi.connectionLost', 'Connection lost') }
          : m
      ))
      setSending(false)
    }
  }

  const handleContinue = () => {
    setInputValue(t('hyperAi.continueMessage', 'Please continue'))
    setTimeout(() => handleSend(), 100)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full">
      {/* Left: Conversation List */}
      <div className={`border-r flex flex-col transition-all duration-200 ${sidebarCollapsed ? 'w-0 overflow-hidden border-r-0' : 'w-64'}`}>
        <div className="p-3 flex items-center gap-2">
          <Button onClick={handleNewConversation} className="flex-1" size="sm">
            <Plus className="w-4 h-4 mr-2" />
            {t('hyperAi.newChat', 'New Chat')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="px-2 shrink-0"
            onClick={() => setSidebarCollapsed(true)}
            title={t('hyperAi.collapseSidebar', 'Collapse sidebar')}
          >
            <PanelLeftClose className="w-4 h-4" />
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {conversations.map(conv => (
              <button
                key={conv.id}
                onClick={() => setCurrentConvId(conv.id)}
                className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  conv.is_bot_conversation
                    ? 'border border-blue-500/30 bg-blue-500/5 mb-1 '
                    : ''
                }${
                  currentConvId === conv.id
                    ? 'bg-secondary text-secondary-foreground'
                    : 'hover:bg-muted text-muted-foreground'
                }`}
              >
                {conv.is_bot_conversation ? (
                  <>
                    <div className="flex items-center gap-2">
                      <BotConvIcon />
                      <span className="truncate font-medium">{conv.title}</span>
                    </div>
                    <div className="flex items-center gap-1.5 mt-1.5 ml-6">
                      {botConfig?.status === 'connected' && <TelegramSmallIcon />}
                      {discordBotConfig?.status === 'connected' && <DiscordSmallIcon />}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="flex items-center gap-2">
                      <MessageSquare className="w-4 h-4 flex-shrink-0" />
                      <span className="truncate">{conv.title}</span>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {conv.message_count} {t('hyperAi.messages', 'messages')}
                    </div>
                  </>
                )}
              </button>
            ))}
          </div>
        </ScrollArea>
      </div>

      {/* Center: Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 relative">
        {sidebarCollapsed && (
          <Button
            variant="ghost"
            size="sm"
            className="absolute top-2 left-2 z-10 px-2"
            onClick={() => setSidebarCollapsed(false)}
            title={t('hyperAi.expandSidebar', 'Expand sidebar')}
          >
            <PanelLeftOpen className="w-4 h-4" />
          </Button>
        )}
        {messages.length === 0 ? (
          <WelcomeMessage
            nickname={nickname}
            t={t}
            onSuggestionClick={(question) => {
              setInputValue(question)
              setTimeout(() => handleSend(), 100)
            }}
          />
        ) : (
          <ScrollArea className="flex-1 p-4">
            <div className="space-y-4 max-w-5xl mx-auto">
              {messages.map((msg, idx) => {
                // Check if this message is a compression point
                const compressionPoint = compressionPoints.find(cp => cp.message_id === msg.id)
                return (
                  <div key={idx}>
                    <MessageBubble
                      message={msg}
                      onContinue={msg.isInterrupted && !sending ? handleContinue : undefined}
                      onToolConfirmation={handleToolConfirmation}
                      t={t}
                    />
                    {compressionPoint && (
                      <div className="flex items-center gap-3 my-4 text-xs text-muted-foreground">
                        <div className="flex-1 border-t border-dashed border-muted-foreground/30" />
                        <span className="px-2 py-1 bg-muted rounded text-[10px]">
                          {t('hyperAi.compressionPoint', 'Context compressed')}
                        </span>
                        <div className="flex-1 border-t border-dashed border-muted-foreground/30" />
                      </div>
                    )}
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>
        )}

        {/* Input Area */}
        <div className="px-4 pb-4 pt-2">
          <div className="max-w-5xl mx-auto relative">
            {imageAttachments.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-2">
                {imageAttachments.map(image => (
                  <div key={image.id} className="group relative h-20 w-20 overflow-hidden rounded-lg border bg-muted">
                    <img
                      src={image.data_url}
                      alt={image.name}
                      className="h-full w-full object-cover"
                    />
                    <button
                      type="button"
                      onClick={() => removeImageAttachment(image.id)}
                      className="absolute right-1 top-1 rounded-full bg-background/90 p-1 text-foreground shadow opacity-90 hover:opacity-100"
                      aria-label={t('common.remove', 'Remove')}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={e => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              onDrop={handleDrop}
              onDragOver={e => e.preventDefault()}
              placeholder={t('hyperAi.inputPlaceholder', 'Type a message...')}
              disabled={sending}
              className="w-full min-h-[80px] max-h-[200px] rounded-xl border border-input bg-transparent px-4 py-3 pb-12 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 resize-y"
              rows={3}
            />
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={e => {
                if (e.target.files) void addImageFiles(e.target.files)
                e.currentTarget.value = ''
              }}
            />
            <div className="absolute bottom-3 left-3 flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full"
                disabled={sending || imageAttachments.length >= MAX_IMAGE_ATTACHMENTS}
                onClick={() => fileInputRef.current?.click()}
                title={t('hyperAi.attachImage', 'Attach image')}
              >
                <ImagePlus className="h-4 w-4" />
              </Button>
              {imageAttachments.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  {imageAttachments.length}/{MAX_IMAGE_ATTACHMENTS}
                </span>
              )}
            </div>
            <div className="absolute bottom-3 right-3 flex items-center gap-2">
              {tokenUsage?.show_warning && (
                <p className="text-xs text-amber-500">
                  {t('hyperAi.contextWarning', 'Context remaining: {{percent}}% · Compressing soon', { percent: Math.max(0, Math.round((1 - tokenUsage.usage_ratio) * 100)) })}
                </p>
              )}
              <Button
                onClick={handleSend}
                disabled={(!inputValue.trim() && imageAttachments.length === 0) || sending}
                size="icon"
                className="rounded-full h-8 w-8 shrink-0"
              >
                {sending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Right: Config Panel */}
      {showConfig && (
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
              <div className="flex items-center">
                <span className="text-muted-foreground shrink-0 w-[72px]">Provider</span>
                <span className="truncate">{profile.llm_provider || 'Not configured'}</span>
              </div>
              <div className="flex items-center">
                <span className="text-muted-foreground shrink-0 w-[72px]">Model</span>
                <span className="truncate">{profile.llm_model || '-'}</span>
              </div>
              {profile.llm_base_url && (
                <div className="flex items-center">
                  <span className="text-muted-foreground shrink-0 w-[72px]">Base URL</span>
                  <span className="truncate">{profile.llm_base_url}</span>
                </div>
              )}
            </div>
          )}

          {/* Memory Entry */}
          <div className="pt-4">
            <button
              onClick={() => setShowMemoryModal(true)}
              className="w-full flex items-center gap-1.5 py-1 rounded-lg text-sm hover:bg-muted/50 transition-colors text-left"
            >
              <Brain className="w-4 h-4 text-primary shrink-0" />
              <span className="text-sm font-medium">{t('hyperAi.memory.button', 'Memory')}</span>
              <ChevronRight className="w-3 h-3 text-muted-foreground ml-auto shrink-0" />
            </button>
          </div>

          <div className="pt-4">
            <div className="flex items-center justify-between mb-1">
              <h4 className="text-sm font-medium flex items-center gap-1.5">
                <svg className="w-4 h-4 shrink-0" viewBox="0 0 1024 1024" fill="currentColor">
                  <path d="M556.8 960H166.4c-25.6 0-51.2-12.8-70.4-25.6-19.2-19.2-32-44.8-32-70.4v-115.2c6.4-19.2 12.8-38.4 32-51.2 12.8-6.4 19.2-12.8 32-12.8s25.6 6.4 44.8 12.8H192c12.8 6.4 19.2 6.4 32 6.4s25.6 0 32-6.4c12.8-6.4 19.2-12.8 25.6-19.2 6.4-6.4 12.8-19.2 19.2-25.6 6.4-12.8 6.4-19.2 6.4-32s0-25.6-6.4-32c-6.4-12.8-12.8-19.2-19.2-25.6s-19.2-12.8-25.6-19.2c-12.8-6.4-19.2-6.4-32-6.4s-19.2 0-32 6.4h-6.4-6.4c-6.4 6.4-19.2 6.4-25.6 12.8-12.8 6.4-25.6 6.4-38.4 6.4-19.2 0-32-12.8-38.4-25.6-6.4-12.8-12.8-25.6-12.8-44.8V390.4c0-25.6 12.8-51.2 32-70.4 19.2-19.2 44.8-32 70.4-32h83.2c-6.4-19.2-6.4-32-6.4-51.2 0-25.6 6.4-51.2 12.8-70.4l38.4-57.6c19.2-19.2 38.4-32 57.6-38.4 25.6-12.8 44.8-12.8 70.4-12.8s51.2 6.4 70.4 12.8l57.6 38.4c19.2 19.2 32 38.4 38.4 57.6 12.8 25.6 12.8 44.8 12.8 70.4 0 19.2 0 38.4-6.4 51.2h25.6c25.6 0 51.2 12.8 70.4 32 19.2 19.2 25.6 44.8 25.6 70.4v19.2c0 12.8-12.8 32-38.4 32-25.6 0-32-12.8-38.4-25.6v-25.6c0-6.4 0-12.8-6.4-19.2-6.4-6.4-6.4-6.4-19.2-6.4H441.6l51.2-64c19.2-19.2 25.6-38.4 25.6-64 0-12.8 0-32-6.4-44.8-6.4-12.8-12.8-25.6-25.6-32-12.8-12.8-19.2-19.2-32-25.6-12.8-6.4-25.6-6.4-44.8-6.4-12.8 0-25.6 0-44.8 6.4-12.8 6.4-25.6 12.8-32 25.6-12.8 12.8-19.2 19.2-25.6 32-6.4 12.8-6.4 25.6-6.4 44.8 0 12.8 0 25.6 6.4 38.4 6.4 12.8 12.8 25.6 19.2 32l51.2 64H153.6c-6.4 0-12.8 0-19.2 6.4-6.4 6.4-6.4 12.8-6.4 19.2v89.6s6.4 0 6.4-6.4c6.4 0 6.4-6.4 12.8-6.4 19.2-6.4 38.4-12.8 64-12.8 19.2 0 44.8 6.4 64 12.8 19.2 6.4 38.4 19.2 51.2 32 12.8 12.8 25.6 32 32 51.2 6.4 19.2 12.8 38.4 12.8 64 0 19.2-6.4 44.8-12.8 64-6.4 19.2-19.2 38.4-32 51.2-12.8 12.8-32 25.6-51.2 32-19.2 6.4-38.4 12.8-64 12.8-19.2 0-44.8-6.4-64-12.8-6.4 0-12.8-6.4-19.2-6.4v96c0 6.4 0 12.8 6.4 19.2 6.4 6.4 12.8 6.4 19.2 6.4h396.8c19.2 6.4 25.6 19.2 25.6 38.4 6.4 25.6 0 32-19.2 38.4z m204.8-76.8c-6.4-6.4-25.6-19.2-32-19.2-6.4 0-25.6 12.8-32 19.2-6.4 6.4-19.2 12.8-25.6 12.8-6.4 0-12.8 0-12.8-6.4l-51.2-25.6c-12.8-12.8-19.2-25.6-12.8-44.8 0 0 6.4-6.4 6.4-12.8 0-12.8-6.4-19.2-12.8-25.6-6.4-6.4-19.2-12.8-25.6-12.8-12.8 0-25.6-12.8-32-32 0 0-6.4-25.6-6.4-44.8 0-19.2 6.4-44.8 6.4-44.8 6.4-19.2 12.8-32 32-32s38.4-19.2 38.4-38.4c0-6.4-6.4-12.8-6.4-12.8-6.4-19.2 0-38.4 12.8-44.8l57.6-32c6.4 0 12.8-6.4 12.8-6.4 12.8 0 19.2 6.4 25.6 12.8 6.4 6.4 25.6 19.2 32 19.2 6.4 0 25.6-12.8 32-19.2 6.4-6.4 19.2-12.8 25.6-12.8 6.4 0 12.8 0 12.8 6.4l51.2 25.6c12.8 12.8 19.2 25.6 12.8 44.8 0 0-6.4 6.4-6.4 12.8 0 19.2 19.2 38.4 38.4 38.4 12.8 0 25.6 12.8 32 32 0 0 6.4 25.6 6.4 44.8 0 19.2-6.4 44.8-6.4 44.8-6.4 19.2-12.8 32-32 32-12.8 0-19.2 6.4-25.6 12.8s-12.8 19.2-12.8 25.6c0 6.4 6.4 12.8 6.4 12.8 6.4 19.2 0 38.4-12.8 44.8l-57.6 32c-6.4 0-12.8 6.4-12.8 6.4-12.8 0-19.2-6.4-25.6-12.8z m-38.4-70.4c19.2 0 32 6.4 51.2 19.2 6.4 6.4 12.8 6.4 12.8 12.8l32-19.2c0-6.4 0-12.8-6.4-25.6 0-44.8 32-83.2 76.8-89.6v-19.2-19.2c-44.8-6.4-76.8-44.8-76.8-89.6 0-6.4 0-19.2 6.4-25.6l-32-19.2-12.8 12.8c-19.2 12.8-32 19.2-51.2 19.2s-32-6.4-51.2-19.2c-6.4-6.4-12.8-6.4-12.8-12.8l-32 19.2c0 6.4 6.4 12.8 6.4 25.6 0 44.8-32 83.2-76.8 89.6v38.4c44.8 6.4 76.8 44.8 76.8 89.6 0 6.4 0 19.2-6.4 25.6l25.6 12.8 12.8-12.8c25.6-6.4 44.8-12.8 57.6-12.8z m0-38.4c-44.8 0-83.2-38.4-83.2-83.2 0-44.8 38.4-83.2 83.2-83.2 44.8 0 83.2 38.4 83.2 83.2 6.4 44.8-32 83.2-83.2 83.2z m0-115.2c-6.4 0-19.2 6.4-25.6 6.4-6.4 6.4-6.4 12.8-6.4 25.6 0 19.2 12.8 32 32 32s32-12.8 32-32-12.8-32-32-32z" />
                </svg>
                {t('hyperAi.skills', 'Skills')}
              </h4>
              {skills.length > 0 && !skillsEditMode && (
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setSkillsEditMode(true)}>
                  <Pencil className="w-3.5 h-3.5" />
                </Button>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground/60 mb-2 px-0.5">
              {t('hyperAi.skillsHint', 'Auto-loaded by AI, or type /command')}
            </p>
            {skills.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {t('hyperAi.skillsLoading', 'Loading...')}
              </p>
            ) : (
              <>
                <div className="space-y-1">
                  {skills.map(skill => {
                    const isEnabled = pendingSkillToggles[skill.name] !== undefined
                      ? pendingSkillToggles[skill.name]
                      : skill.enabled
                    return (
                      <div
                        key={skill.name}
                        className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-muted/50 transition-colors"
                      >
                        {skillsEditMode ? (
                          <Switch
                            checked={isEnabled}
                            onCheckedChange={v => setPendingSkillToggles(prev => ({ ...prev, [skill.name]: v }))}
                            disabled={skillsLoading}
                            className="scale-75 origin-left shrink-0"
                          />
                        ) : activeSkill === skill.name ? (
                          <svg className="w-3.5 h-3.5 shrink-0 text-red-500" viewBox="0 0 1024 1024" fill="currentColor">
                            <path d="M896.512 471.04c-23.04 0-38.4 15.36-38.4 38.4s15.36 38.4 38.4 38.4 38.4-15.36 38.4-38.4c0-23.552-15.36-38.4-38.4-38.4z m-76.8-267.264c-23.04 0-38.4 15.36-38.4 38.4s15.36 38.4 38.4 38.4 38.4-15.36 38.4-38.4-15.36-38.4-38.4-38.4z m-192.512-38.4c23.04 0 38.4-15.36 38.4-38.4s-15.36-38.4-38.4-38.4-38.4 15.36-38.4 38.4 15.36 38.4 38.4 38.4z m-230.4 0c23.04 0 38.4-15.36 38.4-38.4s-15.36-38.4-38.4-38.4-38.4 15.36-38.4 38.4 15.36 38.4 38.4 38.4zM165.888 241.664c-23.04 0-38.4 15.36-38.4 38.4s15.36 38.4 38.4 38.4 38.4-15.36 38.4-38.4-15.36-38.4-38.4-38.4zM127.488 471.04c-23.04 0-38.4 15.36-38.4 38.4s15.36 38.4 38.4 38.4 38.4-15.36 38.4-38.4c0-23.552-15.36-38.4-38.4-38.4z m508.416 203.264c-24.576 16.384-53.76 32.768-82.432 36.864-12.288 4.096-28.672 4.096-41.472 4.096-12.288 0-28.672 0-41.472-4.096-33.28-4.096-57.856-20.48-82.432-36.864-49.664-36.864-82.432-98.304-82.432-163.84 0-114.688 90.624-204.8 206.336-204.8s206.336 90.112 206.336 204.8c0 65.536-32.768 126.976-82.432 163.84z m-58.88 154.112c0 37.888-25.088 62.976-62.976 62.976s-62.976-25.088-62.976-62.976v-59.392c18.944 6.144 44.032 6.144 62.976 6.144s44.032-6.144 62.976-6.144v59.392zM512 247.808c-150.016 0-269.312 118.272-269.312 267.264 0 107.008 61.44 198.656 153.6 240.64v65.024c0 65.024 50.176 114.688 115.2 114.688 65.536 0 115.2-49.664 115.2-114.688v-65.024c92.16-41.984 153.6-133.632 153.6-240.64 1.024-148.992-118.272-267.264-268.288-267.264z" />
                          </svg>
                        ) : (
                          <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${isEnabled ? 'bg-green-500' : 'bg-muted-foreground/30'}`} />
                        )}
                        <span className="text-xs truncate flex-1">
                          {t(`hyperAi.skillNames.${skill.name}`, skill.name)}
                        </span>
                        <span className="text-[10px] text-muted-foreground/50 shrink-0 font-mono">{skill.command}</span>
                      </div>
                    )
                  })}
                </div>
                {skillsEditMode && (
                  <div className="flex gap-2 pt-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleSkillsEditCancel}
                      className="h-7 px-3 text-xs"
                    >
                      {t('hyperAi.skillsCancel', 'Cancel')}
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleSkillsEditSave}
                      disabled={skillsLoading}
                      className="h-7 px-3 text-xs"
                    >
                      {t('hyperAi.skillsSave', 'Save')}
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>

          {/* External Tools */}
          {externalTools.length > 0 && (
            <div className="pt-4">
              <h4 className="text-sm font-medium flex items-center gap-1.5 mb-2">
                <Wrench className="w-4 h-4 shrink-0" />
                {t('hyperAi.tools', 'Tools')}
              </h4>
              <div className="space-y-1">
                {externalTools.map(tool => (
                  <div
                    key={tool.name}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/30 hover:bg-muted/50 cursor-pointer transition-colors"
                    onClick={() => { setSelectedTool(tool); setShowToolModal(true) }}
                  >
                    <SearchIcon className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                    <span className="text-xs truncate flex-1">
                      {currentLang === 'zh' ? tool.display_name_zh : tool.display_name}
                    </span>
                    {tool.configured ? (
                      <span className="w-2 h-2 rounded-full bg-green-500 shrink-0"></span>
                    ) : (
                      <span className="text-[10px] text-primary shrink-0">
                        {t('tools.setup', 'Setup')}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Bot Integrations */}
          <div className="pt-4">
            <h4 className="text-sm font-medium flex items-center gap-1.5 mb-2">
              <Blocks className="w-4 h-4 shrink-0" />
              {t('hyperAi.integrations', 'Integrations')}
              <button
                onClick={() => setShowNotificationModal(true)}
                className="ml-auto flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-primary/10 hover:bg-primary/20 transition-colors"
                title={t('bot.notificationSettings', 'Push Notifications')}
              >
                <NotificationBellSmallIcon />
                {notificationCount > 0 && (
                  <span className="text-[10px] text-primary font-medium min-w-[14px] text-center">
                    {notificationCount}
                  </span>
                )}
              </button>
            </h4>
            <div className="space-y-2">
              {/* Telegram Bot */}
              <div
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/30 hover:bg-muted/50 cursor-pointer transition-colors"
                onClick={() => setShowBotModal(true)}
              >
                <TelegramSmallIcon />
                <span className="text-xs">{t('hyperAi.telegramBot', 'Telegram Bot')}</span>
                {botConfig && botConfig.status === 'connected' ? (
                  <>
                    <span className="ml-auto text-[10px] text-muted-foreground">@{botConfig.bot_username}</span>
                    <span className="w-2 h-2 rounded-full bg-green-500"></span>
                  </>
                ) : (
                  <span className="ml-auto text-[10px] text-primary">
                    {t('bot.setup', 'Setup')}
                  </span>
                )}
              </div>
              {/* Discord Bot - Coming Soon */}
              <div
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/30 hover:bg-muted/50 cursor-pointer transition-colors"
                onClick={() => setShowDiscordBotModal(true)}
              >
                <DiscordSmallIcon />
                <span className="text-xs">{t('hyperAi.discordBot', 'Discord Bot')}</span>
                {discordBotConfig && discordBotConfig.status === 'connected' ? (
                  <>
                    <span className="ml-auto text-[10px] text-muted-foreground">@{discordBotConfig.bot_username}</span>
                    <span className="w-2 h-2 rounded-full bg-green-500"></span>
                  </>
                ) : (
                  <span className="ml-auto text-[10px] text-primary">
                    {t('bot.setup', 'Setup')}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* LLM Config Modal */}
      <LLMConfigModal
        open={showConfigModal}
        onClose={() => setShowConfigModal(false)}
        providers={providers}
        currentProfile={profile}
        onSaved={fetchProfile}
      />

      {/* Memory Modal */}
      <MemoryModal
        open={showMemoryModal}
        onClose={() => setShowMemoryModal(false)}
      />

      {/* Bot Integration Modal */}
      <BotIntegrationModal
        open={showBotModal}
        onClose={() => setShowBotModal(false)}
        platform="telegram"
        onConnected={fetchBotConfig}
        currentBotUsername={botConfig?.status === 'connected' ? botConfig.bot_username : undefined}
      />

      {/* Discord Bot Integration Modal */}
      <BotIntegrationModal
        open={showDiscordBotModal}
        onClose={() => setShowDiscordBotModal(false)}
        platform="discord"
        onConnected={fetchDiscordBotConfig}
        currentBotUsername={discordBotConfig?.status === 'connected' ? discordBotConfig.bot_username : undefined}
        currentBotAppId={discordBotConfig?.bot_app_id}
      />

      {/* Notification Config Modal */}
      <NotificationConfigModal
        open={showNotificationModal}
        onClose={() => setShowNotificationModal(false)}
        onConfigChange={(count) => setNotificationCount(count)}
      />
      <ToolConfigModal
        open={showToolModal}
        onClose={() => { setShowToolModal(false); setSelectedTool(null) }}
        tool={selectedTool}
        onSaved={fetchExternalTools}
      />
    </div>
  )
}
