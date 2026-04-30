import type { ComponentType } from 'react'
import { create } from 'zustand'

export interface MenuItem {
  key: string
  label: string
  icon?: ComponentType<any>
  variant?: 'default' | 'danger'
  checked?: boolean
  disabled?: boolean
  action?: (itemId: string) => void
}

interface ContextMenuStore {
  visible: boolean
  selectedItemId?: string
  targetElement: HTMLElement | null
  items: MenuItem[]
  onItemClick?: (itemKey: string, itemId: string) => void
  onCloseHandler?: (itemId: string) => void
  show: (
    itemId: string,
    element: HTMLElement,
    items: MenuItem[],
    onMenuItemClick?: (itemKey: string, itemId: string) => void,
    onClose?: (itemId: string) => void,
  ) => void
  hide: () => void
  handleItemClick: (item: MenuItem) => void
}

export const useContextMenu = create<ContextMenuStore>((set, get) => ({
  visible: false,
  selectedItemId: undefined,
  targetElement: null,
  items: [],
  onItemClick: undefined,
  onCloseHandler: undefined,
  show: (itemId, element, items, onMenuItemClick, onClose) => {
    // ensure prior menu is closed first so its onClose runs
    get().hide()
    set({
      visible: true,
      selectedItemId: itemId,
      targetElement: element,
      items,
      onItemClick: onMenuItemClick,
      onCloseHandler: onClose,
    })
  },
  hide: () => {
    const state = get()
    const id = state.selectedItemId
    const cb = state.onCloseHandler
    set({
      visible: false,
      selectedItemId: undefined,
      targetElement: null,
      items: [],
      onItemClick: undefined,
      onCloseHandler: undefined,
    })
    if (cb && id) cb(id)
  },
  handleItemClick: (item) => {
    if (item.disabled) return
    const state = get()
    const id = state.selectedItemId
    if (id) {
      state.onItemClick?.(item.key, id)
      item.action?.(id)
    }
    get().hide()
  },
}))

export const createMenuItem = (
  key: string,
  label: string,
  options: Partial<Omit<MenuItem, 'key' | 'label'>> = {},
): MenuItem => ({ key, label, variant: 'default', ...options })

export const createDangerMenuItem = (
  key: string,
  label: string,
  options: Partial<Omit<MenuItem, 'key' | 'label' | 'variant'>> = {},
): MenuItem => ({ key, label, variant: 'danger', ...options })

export const createSeparator = (): MenuItem => ({ key: 'separator', label: '', disabled: true })
