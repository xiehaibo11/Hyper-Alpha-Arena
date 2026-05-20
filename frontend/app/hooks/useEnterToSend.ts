import { useEffect } from 'react'

function isTextInput(element: EventTarget | null): element is HTMLInputElement {
  if (!(element instanceof HTMLInputElement)) return false
  const type = (element.type || 'text').toLowerCase()
  return ['text', 'search', 'email', 'url', 'tel'].includes(type)
}

function hasComposerPlaceholder(element: HTMLInputElement | HTMLTextAreaElement): boolean {
  const placeholder = (element.getAttribute('placeholder') || '').toLowerCase()
  return /message|question|chat|ask|describe|strategy|signal|analy[sz]e|prompt|program|消息|问题|提问|输入|描述|策略|信号|分析/.test(placeholder)
}

function isChatTextarea(element: HTMLTextAreaElement): boolean {
  if (element.classList.contains('pb-12') && element.classList.contains('resize-y')) {
    return true
  }
  return hasComposerPlaceholder(element)
}

function isVisible(button: HTMLButtonElement): boolean {
  return !button.disabled && button.getClientRects().length > 0
}

function buttonLooksLikeSend(button: HTMLButtonElement): boolean {
  const label = [
    button.getAttribute('aria-label'),
    button.getAttribute('title'),
    button.textContent,
  ].join(' ').toLowerCase()

  if (/send|submit|发送|提交/.test(label)) return true

  const className = typeof button.className === 'string' ? button.className : ''
  return Boolean(button.querySelector('svg')) && className.includes('rounded-full')
}

function findSendButton(control: HTMLElement): HTMLButtonElement | null {
  let scope = control.parentElement

  for (let depth = 0; scope && depth < 4; depth += 1, scope = scope.parentElement) {
    const buttons = Array.from(scope.querySelectorAll('button')).filter(isVisible)
    const likelyButtons = buttons.filter(buttonLooksLikeSend)

    if (likelyButtons.length === 1) return likelyButtons[0]
    if (buttons.length === 1 && buttons[0].querySelector('svg')) return buttons[0]
  }

  return null
}

function shouldUseEnterToSend(target: EventTarget | null): target is HTMLInputElement | HTMLTextAreaElement {
  if (target instanceof HTMLTextAreaElement) return isChatTextarea(target)
  if (isTextInput(target)) return hasComposerPlaceholder(target)
  return false
}

export function useEnterToSend() {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== 'Enter' ||
        event.shiftKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        event.isComposing ||
        event.keyCode === 229
      ) {
        return
      }

      if (!shouldUseEnterToSend(event.target)) return
      if (event.target.disabled || event.target.readOnly || !event.target.value.trim()) return

      const sendButton = findSendButton(event.target)
      if (!sendButton) return

      event.preventDefault()
      sendButton.click()
    }

    document.addEventListener('keydown', handleKeyDown, true)
    return () => document.removeEventListener('keydown', handleKeyDown, true)
  }, [])
}
