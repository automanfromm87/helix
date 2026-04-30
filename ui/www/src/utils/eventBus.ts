type Handler<T = unknown> = (payload: T) => void

class EventBus {
  private listeners = new Map<string, Set<Handler<any>>>()

  on<T = unknown>(event: string, handler: Handler<T>): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(handler as Handler<any>)
    return () => this.off(event, handler)
  }

  off<T = unknown>(event: string, handler?: Handler<T>): void {
    if (!handler) {
      this.listeners.delete(event)
      return
    }
    this.listeners.get(event)?.delete(handler as Handler<any>)
  }

  emit<T = unknown>(event: string, payload?: T): void {
    this.listeners.get(event)?.forEach((handler) => handler(payload))
  }
}

export const eventBus = new EventBus()
