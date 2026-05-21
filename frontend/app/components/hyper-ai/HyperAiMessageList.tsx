import type { RefObject } from 'react'
import type { TFunction } from 'i18next'
import { ScrollArea } from '@/components/ui/scroll-area'
import MessageBubble from './MessageBubble'
import type { Message } from './HyperAiChatTypes'
import type { CompressionPoint } from './HyperAiPageSupport'

interface Props {
  messages: Message[]
  compressionPoints: CompressionPoint[]
  sending: boolean
  messagesEndRef: RefObject<HTMLDivElement>
  t: TFunction
  onContinue: () => void
  onToolConfirmation: (taskId: string, confirmationId: string, confirmed: boolean) => void
}

export default function HyperAiMessageList({
  messages,
  compressionPoints,
  sending,
  messagesEndRef,
  t,
  onContinue,
  onToolConfirmation,
}: Props) {
  return (
    <ScrollArea className="flex-1 p-4">
      <div className="space-y-4 max-w-5xl mx-auto">
        {messages.map((msg, idx) => {
          const compressionPoint = compressionPoints.find(cp => cp.message_id === msg.id)
          return (
            <div key={idx}>
              <MessageBubble
                message={msg}
                onContinue={msg.isInterrupted && !sending ? onContinue : undefined}
                onToolConfirmation={onToolConfirmation}
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
  )
}
