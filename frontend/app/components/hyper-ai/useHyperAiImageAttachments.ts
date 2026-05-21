import { useState } from 'react'
import type { ClipboardEvent, DragEvent } from 'react'
import type { ChatImageAttachment } from './HyperAiChatTypes'
import {
  MAX_IMAGE_ATTACHMENTS,
  MAX_IMAGE_BYTES,
  readImageAttachment,
} from './HyperAiPageSupport'

export function useHyperAiImageAttachments() {
  const [imageAttachments, setImageAttachments] = useState<ChatImageAttachment[]>([])

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

  const clearImageAttachments = () => setImageAttachments([])

  return {
    imageAttachments,
    setImageAttachments,
    addImageFiles,
    handlePaste,
    handleDrop,
    removeImageAttachment,
    clearImageAttachments,
  }
}
