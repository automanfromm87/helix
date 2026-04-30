/** Read parent element of a selector or DOM element. */
export function getParentElement(
  selector: string | HTMLElement | Element,
  parentSelector?: string,
): HTMLElement | null {
  let element: Element | null = null

  if (typeof selector === 'string') {
    element = document.querySelector(selector)
  } else {
    element = selector
  }

  if (!element) return null

  if (parentSelector) {
    const parent = element.closest(parentSelector)
    return (parent as HTMLElement) ?? null
  }

  return element.parentElement ?? null
}

/** Copy text to clipboard with a textarea fallback. */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch (e) {
      // fall through
    }
  }

  try {
    const activeElement = document.activeElement as HTMLElement | null
    const textArea = document.createElement('textarea')
    textArea.value = text
    textArea.style.position = 'fixed'
    textArea.style.top = '-9999px'
    textArea.style.left = '-9999px'
    textArea.style.opacity = '0'
    textArea.setAttribute('readonly', '')
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textArea)
    activeElement?.focus?.()
    return ok
  } catch (e) {
    return false
  }
}
