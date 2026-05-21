import { useState, useEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { PanelLeftOpen } from 'lucide-react'
import { pollAiStream } from '@/lib/pollAiStream'
import HyperAiChatInput from './HyperAiChatInput'
import HyperAiConfigPanel from './HyperAiConfigPanel'
import HyperAiConversationSidebar from './HyperAiConversationSidebar'
import HyperAiMessageList from './HyperAiMessageList'
import { createToolConfirmationHandler } from './hyperAiToolConfirmation'
import type {
  Message,
  ToolCallEntry,
  ToolCallLogEntry,
} from './HyperAiChatTypes'

import { WelcomeMessage } from './HyperAiPageSupport'
import type {
  CompressionPoint,
  TokenUsage,
} from './HyperAiPageSupport'
import { useHyperAiImageAttachments } from './useHyperAiImageAttachments'

export default function HyperAiPage() {
  const { t, i18n } = useTranslation()
  const [currentConvId, setCurrentConvId] = useState<number | null>(null)
  const [currentConversationArchived, setCurrentConversationArchived] = useState(false)
  const [conversationRefreshKey, setConversationRefreshKey] = useState(0)
  const [messages, setMessages] = useState<Message[]>([])
  const [compressionPoints, setCompressionPoints] = useState<CompressionPoint[]>([])
  const [tokenUsage, setTokenUsage] = useState<TokenUsage | null>(null)
  const [inputValue, setInputValue] = useState('')
  const [sending, setSending] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [nickname, setNickname] = useState<string>('')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [activeSkill, setActiveSkill] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const {
    imageAttachments,
    setImageAttachments,
    addImageFiles,
    handlePaste,
    handleDrop,
    removeImageAttachment,
    clearImageAttachments,
  } = useHyperAiImageAttachments()
  const handleToolConfirmation = createToolConfirmationHandler(setMessages)

  const currentLang = i18n.language?.startsWith('zh') ? 'zh' : 'en'

  useEffect(() => {
    fetchProfile()
  }, [])

  useEffect(() => {
    if (currentConvId && !sending) {
      fetchMessages(currentConvId)
    }
  }, [currentConvId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  useEffect(() => {
    const pending = localStorage.getItem('hyper-ai-pending-prompt')
    if (pending) {
      localStorage.removeItem('hyper-ai-pending-prompt')
      setInputValue(pending)
      setTimeout(() => textareaRef.current?.focus(), 200)
    }
  }, [])

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

  const fetchProfile = async () => {
    try {
      const res = await fetch('/api/hyper-ai/profile')
      const data = await res.json()
      if (data.nickname) {
        setNickname(data.nickname)
      }
    } catch (e) {
      console.error('Failed to fetch profile:', e)
    }
  }

  const handleNewConversation = () => {
    setCurrentConvId(null)
    setCurrentConversationArchived(false)
    setMessages([])
    setCompressionPoints([])
    setTokenUsage(null)
    setActiveSkill(null)
    clearImageAttachments()
  }

  const handleSend = async () => {
    if ((!inputValue.trim() && imageAttachments.length === 0) || sending || currentConversationArchived) return

    const pendingImages = imageAttachments
    const userMessage = inputValue.trim() || (currentLang === 'zh' ? '请分析这张图片。' : 'Please analyze the attached image.')
    setInputValue('')
    clearImageAttachments()
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
          setCurrentConversationArchived(false)
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
            if (data.conversation_id) {
              setCurrentConvId(data.conversation_id)
              setCurrentConversationArchived(false)
            }
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
      setConversationRefreshKey(value => value + 1)
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

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full">
      {/* Left: Conversation List */}
      <HyperAiConversationSidebar
        collapsed={sidebarCollapsed}
        currentConvId={currentConvId}
        refreshKey={conversationRefreshKey}
        t={t}
        onCollapse={() => setSidebarCollapsed(true)}
        onNewConversation={handleNewConversation}
        onSelectConversation={(id, archived) => {
          setCurrentConvId(id)
          setCurrentConversationArchived(archived)
        }}
        onArchivedCurrent={handleNewConversation}
      />

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
          <HyperAiMessageList
            messages={messages}
            compressionPoints={compressionPoints}
            sending={sending}
            messagesEndRef={messagesEndRef}
            t={t}
            onContinue={handleContinue}
            onToolConfirmation={handleToolConfirmation}
          />
        )}

        <HyperAiChatInput
          value={inputValue}
          images={imageAttachments}
          sending={sending}
          archived={currentConversationArchived}
          tokenUsage={tokenUsage}
          textareaRef={textareaRef}
          fileInputRef={fileInputRef}
          t={t}
          onValueChange={setInputValue}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onDrop={handleDrop}
          onAttachFiles={(files) => void addImageFiles(files)}
          onRemoveImage={removeImageAttachment}
          onSend={handleSend}
        />
      </div>

      <HyperAiConfigPanel activeSkill={activeSkill} currentLang={currentLang} t={t} />
    </div>
  )
}
