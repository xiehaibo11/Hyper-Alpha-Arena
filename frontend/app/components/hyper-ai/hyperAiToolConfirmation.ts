import type { Dispatch, SetStateAction } from 'react'
import type { Message } from './HyperAiChatTypes'

type SetMessages = Dispatch<SetStateAction<Message[]>>

export function createToolConfirmationHandler(setMessages: SetMessages) {
  return async (taskId: string, confirmationId: string, confirmed: boolean) => {
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
}
