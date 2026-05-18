import { memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Play,
  User,
  Wrench,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import PacmanLoader from '@/components/ui/pacman-loader'
import type { CreatedEntityCard, Message, ToolCallLogEntry } from './HyperAiChatTypes'

interface MessageBubbleProps {
  message: Message
  onContinue?: () => void
  onToolConfirmation: (taskId: string, confirmationId: string, confirmed: boolean) => void
  t: (key: string, fallback?: string) => string
}

const MessageBubble = memo(function MessageBubble({
  message,
  onContinue,
  onToolConfirmation,
  t,
}: MessageBubbleProps) {
  const [expandedCards, setExpandedCards] = useState<Record<string, boolean>>({})
  const isUser = message.role === 'user'

  const toolCallsLog: ToolCallLogEntry[] = message.tool_calls_log
    ? (() => { try { return JSON.parse(message.tool_calls_log) } catch { return [] } })()
    : []

  const createdEntities: CreatedEntityCard[] = toolCallsLog
    .filter(entry => {
      if (!['save_prompt', 'save_program', 'save_signal_pool', 'create_ai_trader', 'save_factor'].includes(entry.tool)) return false
      try {
        const result = JSON.parse(entry.result)
        return result.success === true && result.view_url
      } catch {
        return false
      }
    })
    .map(entry => {
      const result = JSON.parse(entry.result)
      const toolToType: Record<string, CreatedEntityCard['type']> = {
        save_prompt: 'prompt',
        save_program: 'program',
        save_signal_pool: 'signal_pool',
        create_ai_trader: 'ai_trader',
        save_factor: 'factor'
      }
      return {
        type: toolToType[entry.tool],
        id: result.prompt_id || result.program_id || result.pool_id || result.trader_id || result.factor_id,
        name: result.name || result.pool_name || result.trader_name,
        content: result.template_text || result.code || result.expression || (result.signals ? JSON.stringify(result.signals, null, 2) : undefined),
        viewUrl: result.view_url
      } as CreatedEntityCard
    })

  const toggleCardExpanded = (cardId: string) => {
    setExpandedCards(prev => ({ ...prev, [cardId]: !prev[cardId] }))
  }

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
        isUser ? 'bg-primary text-primary-foreground' : 'bg-muted'
      }`}>
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      <div className={`max-w-[80%] rounded-lg px-4 py-3 ${
        isUser
          ? 'bg-primary text-primary-foreground'
          : 'bg-muted min-w-[400px]'
      }`}>
        {message.isStreaming && message.statusText && (
          <div className="flex items-center gap-2 text-xs mb-2 text-primary animate-pulse">
            <PacmanLoader className="w-6 h-3" />
            <span>{message.statusText}</span>
          </div>
        )}

        {message.isStreaming && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2 text-xs bg-background/50 rounded p-2 max-h-32 overflow-y-auto">
            {message.toolCalls.filter(e => e.type !== 'confirmation_required').slice(-8).map((entry, idx) => (
              <div key={idx} className="mb-1 last:mb-0">
                {entry.type === 'tool_call' && (
                  <span className="text-blue-500">→ {entry.name}</span>
                )}
                {entry.type === 'tool_result' && (
                  <span className="text-green-500">
                    ← {entry.name}: {entry.resultStatus && entry.resultStatus !== 'success' ? entry.resultStatus : 'done'}
                    {typeof entry.durationMs === 'number' ? ` (${entry.durationMs}ms)` : ''}
                    {entry.parallel ? ' parallel' : ''}
                  </span>
                )}
                {entry.type === 'reasoning' && (
                  <span className="text-gray-500 italic">{(entry.content || '').slice(0, 100)}...</span>
                )}
                {entry.type === 'subagent_progress' && entry.step === 'reasoning' && (
                  <span className="text-gray-500 italic">[{entry.subagent}] {(entry.content || '').slice(0, 100)}...</span>
                )}
                {entry.type === 'subagent_progress' && entry.step === 'tool_call' && (
                  <span className="text-blue-400">[{entry.subagent}] → {entry.tool}</span>
                )}
                {entry.type === 'subagent_progress' && entry.step === 'tool_result' && (
                  <span className="text-green-400">[{entry.subagent}] ← {entry.tool}: done</span>
                )}
                {entry.type === 'subagent_progress' && entry.step === 'tool_round' && (
                  <span className="text-orange-400">[{entry.subagent}] {t('hyperAi.subagentRound', 'round')}{entry.round ? ` ${entry.round}${entry.max_rounds ? `/${entry.max_rounds}` : ''}` : ''}</span>
                )}
                {entry.type === 'tool_error' && (
                  <span className="text-amber-500">[{entry.name}] {entry.message || entry.severity}</span>
                )}
              </div>
            ))}
          </div>
        )}

        {message.isStreaming && message.toolCalls?.filter(e => e.type === 'confirmation_required').map((entry, idx) => (
          <div key={`confirm-${idx}`} className="mb-2 rounded border border-amber-300 bg-amber-50 p-3 text-amber-950 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100">
            <div className="mb-1 flex items-center gap-1 text-sm font-medium">
              <AlertCircle className="h-4 w-4" />
              {t('hyperAi.confirmationRequired', 'Confirmation required')}
            </div>
            <div className="mb-2 text-xs text-muted-foreground">
              {entry.description || entry.name}
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                className="h-7 px-2 text-xs"
                disabled={entry.status !== 'pending' || !entry.taskId || !entry.confirmationId}
                onClick={() => entry.taskId && entry.confirmationId && onToolConfirmation(entry.taskId, entry.confirmationId, true)}
              >
                <CheckCircle2 className="mr-1 h-3 w-3" />
                {entry.status === 'confirmed' ? t('hyperAi.confirmed', 'Confirmed') : t('common.confirm', 'Confirm')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={entry.status !== 'pending' || !entry.taskId || !entry.confirmationId}
                onClick={() => entry.taskId && entry.confirmationId && onToolConfirmation(entry.taskId, entry.confirmationId, false)}
              >
                <X className="mr-1 h-3 w-3" />
                {entry.status === 'cancelled' ? t('hyperAi.cancelled', 'Cancelled') : t('common.cancel', 'Cancel')}
              </Button>
              {entry.status === 'failed' && (
                <span className="self-center text-[11px] text-destructive">
                  {t('hyperAi.confirmationFailed', 'Confirmation failed')}
                </span>
              )}
            </div>
          </div>
        ))}

        {!message.isStreaming && toolCallsLog.length > 0 && (
          <details className="mb-3 text-xs border rounded-md">
            <summary className="px-3 py-2 cursor-pointer bg-muted/50 hover:bg-muted font-medium flex items-center gap-1">
              <Wrench className="w-3 h-3" />
              {t('hyperAi.toolCallsDetail', 'Tool calls')} ({toolCallsLog.length})
            </summary>
            <div className="p-3 space-y-3 max-h-96 overflow-y-auto">
              {toolCallsLog.map((entry, idx) => (
                <div key={idx} className="border-b pb-2 last:border-b-0 last:pb-0">
                  <div className="font-medium text-blue-600 dark:text-blue-400 mb-1">
                    {idx + 1}. {entry.tool}
                  </div>
                  {(entry.status || entry.risk_level) && (
                    <div className="mb-1 ml-2 flex flex-wrap gap-1 text-[11px]">
                      {entry.status && (
                        <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                          status: {entry.status}{entry.code ? `/${entry.code}` : ''}
                        </span>
                      )}
                      {entry.risk_level && (
                        <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                          risk: {entry.risk_level}
                        </span>
                      )}
                      {typeof entry.duration_ms === 'number' && (
                        <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                          time: {entry.duration_ms}ms
                        </span>
                      )}
                      {entry.schema_validated && (
                        <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                          schema
                        </span>
                      )}
                      {entry.concurrency_safe && (
                        <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                          parallel-safe
                        </span>
                      )}
                      {entry.execution_mode && (
                        <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                          mode: {entry.execution_mode}
                        </span>
                      )}
                    </div>
                  )}
                  {entry.args && Object.keys(entry.args).length > 0 && (
                    <div className="mb-1 ml-2 text-muted-foreground">
                      {Object.entries(entry.args).map(([key, value]) => (
                        <div key={key}>{key}: {JSON.stringify(value)}</div>
                      ))}
                    </div>
                  )}
                  <div className="ml-2 text-green-600 dark:text-green-400">
                    Result: {entry.result.length > 200 ? entry.result.slice(0, 200) + '...' : entry.result}
                  </div>
                </div>
              ))}
            </div>
          </details>
        )}

        {!message.isStreaming && createdEntities.length > 0 && (
          <div className="mb-3 space-y-2">
            {createdEntities.map(entity => {
              const cardId = `${entity.type}-${entity.id}`
              const isExpanded = expandedCards[cardId]
              const typeLabels: Record<CreatedEntityCard['type'], { label: string; icon: string; color: string }> = {
                prompt: { label: t('hyperAi.createdPrompt', 'Prompt Created'), icon: '📝', color: 'border-l-green-500' },
                program: { label: t('hyperAi.createdProgram', 'Program Created'), icon: '🐍', color: 'border-l-blue-500' },
                signal_pool: { label: t('hyperAi.createdSignalPool', 'Signal Pool Created'), icon: '📊', color: 'border-l-purple-500' },
                ai_trader: { label: t('hyperAi.createdAiTrader', 'AI Trader Created'), icon: '🤖', color: 'border-l-amber-500' },
                factor: { label: t('hyperAi.createdFactor', 'Factor Saved'), icon: '📐', color: 'border-l-violet-500' }
              }
              const { label, icon, color } = typeLabels[entity.type]

              return (
                <div key={cardId} className={`border rounded-lg border-l-4 ${color} bg-background text-foreground`}>
                  <div className="px-3 py-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span>{icon}</span>
                      <span className="text-sm font-medium text-green-600 dark:text-green-400">✓ {label}</span>
                    </div>
                  </div>

                  <div className="px-3 pb-2">
                    <div className="text-sm mb-2">
                      <span className="text-muted-foreground">{t('hyperAi.entityName', 'Name')}:</span>{' '}
                      <span className="font-medium">{entity.name}</span>
                      <span className="text-muted-foreground ml-2">(ID: {entity.id})</span>
                    </div>

                    {entity.content && (
                      <div className="mb-2">
                        <button
                          onClick={() => toggleCardExpanded(cardId)}
                          className="text-xs text-primary hover:underline flex items-center gap-1"
                        >
                          {isExpanded ? (
                            <><ChevronDown className="w-3 h-3" />{t('hyperAi.hideContent', 'Hide content')}</>
                          ) : (
                            <><ChevronRight className="w-3 h-3" />{t('hyperAi.viewContent', 'View content')}</>
                          )}
                        </button>
                        {isExpanded && (
                          <div className="mt-2 max-h-64 overflow-y-auto rounded border bg-muted/30 p-2">
                            <pre className="text-xs whitespace-pre-wrap font-mono">{entity.content}</pre>
                          </div>
                        )}
                      </div>
                    )}

                    <a
                      href={entity.viewUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-primary hover:underline flex items-center gap-1"
                    >
                      {t('hyperAi.viewInPage', 'View in page')} →
                    </a>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {!message.isStreaming && message.reasoning_snapshot && (
          <details className="mb-3 text-xs border rounded-md">
            <summary className="px-3 py-2 cursor-pointer bg-muted/50 hover:bg-muted font-medium">
              {t('hyperAi.reasoningProcess', 'Reasoning process')}
            </summary>
            <div className="p-3 max-h-96 overflow-y-auto">
              <pre className="whitespace-pre-wrap text-muted-foreground">{message.reasoning_snapshot}</pre>
            </div>
          </details>
        )}

        {message.attachments && message.attachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {message.attachments.map(image => (
              <a
                key={image.id}
                href={image.data_url}
                target="_blank"
                rel="noopener noreferrer"
                className="block h-28 w-28 overflow-hidden rounded-md border border-white/20 bg-background/30"
                title={image.name}
              >
                <img src={image.data_url} alt={image.name} className="h-full w-full object-cover" />
              </a>
            ))}
          </div>
        )}

        <div className={`text-sm prose prose-sm max-w-none ${
          isUser ? 'prose-invert' : 'dark:prose-invert'
        }`}>
          {message.content ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => {
                  const isInternal = href?.startsWith('/') || href?.startsWith('#')
                  return (
                    <a
                      href={href}
                      target="_blank"
                      rel={isInternal ? undefined : 'noopener noreferrer'}
                      className={isUser
                        ? 'text-white underline hover:text-white/80'
                        : 'text-primary hover:underline'
                      }
                    >
                      {children}
                    </a>
                  )
                }
              }}
            >
              {message.content}
            </ReactMarkdown>
          ) : message.isStreaming ? (
            <span className="text-muted-foreground italic">{t('hyperAi.generating', 'Generating...')}</span>
          ) : null}
        </div>

        {message.isStreaming && message.content && (
          <span className="inline-block w-2 h-4 bg-current animate-pulse ml-1" />
        )}

        {message.isInterrupted && onContinue && (
          <div className="mt-3 pt-3 border-t border-border/50">
            <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400 mb-2">
              <AlertCircle className="w-3 h-3" />
              <span>
                {t('hyperAi.interruptedAt', 'Interrupted at round {{round}}').replace('{{round}}', String(message.interruptedRound || '?'))}
              </span>
            </div>
            <Button size="sm" variant="outline" onClick={onContinue} className="text-xs">
              <Play className="w-3 h-3 mr-1" />
              {t('hyperAi.continueButton', 'Continue')}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
})

export default MessageBubble
