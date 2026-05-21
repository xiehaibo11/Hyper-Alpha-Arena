import type { ClipboardEvent, DragEvent, KeyboardEvent, RefObject } from 'react'
import type { TFunction } from 'i18next'
import { ImagePlus, Loader2, Send, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ChatImageAttachment } from './HyperAiChatTypes'
import {
  MAX_IMAGE_ATTACHMENTS,
  type TokenUsage,
} from './HyperAiPageSupport'

interface Props {
  value: string
  images: ChatImageAttachment[]
  sending: boolean
  archived: boolean
  tokenUsage: TokenUsage | null
  textareaRef: RefObject<HTMLTextAreaElement>
  fileInputRef: RefObject<HTMLInputElement>
  t: TFunction
  onValueChange: (value: string) => void
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void
  onPaste: (e: ClipboardEvent<HTMLTextAreaElement>) => void
  onDrop: (e: DragEvent<HTMLTextAreaElement>) => void
  onAttachFiles: (files: FileList) => void
  onRemoveImage: (id: string) => void
  onSend: () => void
}

export default function HyperAiChatInput({
  value,
  images,
  sending,
  archived,
  tokenUsage,
  textareaRef,
  fileInputRef,
  t,
  onValueChange,
  onKeyDown,
  onPaste,
  onDrop,
  onAttachFiles,
  onRemoveImage,
  onSend,
}: Props) {
  const canSend = (value.trim() || images.length > 0) && !sending && !archived

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="max-w-5xl mx-auto relative">
        {archived && (
          <div className="mb-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            {t('hyperAi.archivedReadOnly', 'This archived chat is read-only. Restore it before sending new messages.')}
          </div>
        )}
        {images.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {images.map(image => (
              <div key={image.id} className="group relative h-20 w-20 overflow-hidden rounded-lg border bg-muted">
                <img src={image.data_url} alt={image.name} className="h-full w-full object-cover" />
                <button
                  type="button"
                  onClick={() => onRemoveImage(image.id)}
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
          value={value}
          onChange={e => onValueChange(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          onDrop={onDrop}
          onDragOver={e => e.preventDefault()}
          placeholder={archived ? t('hyperAi.archivedInputPlaceholder', 'Archived chat') : t('hyperAi.inputPlaceholder', 'Type a message...')}
          disabled={sending || archived}
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
            if (e.target.files) onAttachFiles(e.target.files)
            e.currentTarget.value = ''
          }}
        />
        <div className="absolute bottom-3 left-3 flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-full"
            disabled={sending || archived || images.length >= MAX_IMAGE_ATTACHMENTS}
            onClick={() => fileInputRef.current?.click()}
            title={t('hyperAi.attachImage', 'Attach image')}
          >
            <ImagePlus className="h-4 w-4" />
          </Button>
          {images.length > 0 && (
            <span className="text-xs text-muted-foreground">
              {images.length}/{MAX_IMAGE_ATTACHMENTS}
            </span>
          )}
        </div>
        <div className="absolute bottom-3 right-3 flex items-center gap-2">
          {tokenUsage?.show_warning && (
            <p className="text-xs text-amber-500">
              {t('hyperAi.contextWarning', 'Context remaining: {{percent}}% · Compressing soon', {
                percent: Math.max(0, Math.round((1 - tokenUsage.usage_ratio) * 100)),
              })}
            </p>
          )}
          <Button
            onClick={onSend}
            disabled={!canSend}
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
  )
}
