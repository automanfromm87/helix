/**
 * Minimal RFB shape surface we rely on. The upstream package ships no
 * .d.ts; @types/novnc__novnc isn't published. Keep this in sync with
 * what VNCViewer actually calls.
 */
declare module '@novnc/novnc' {
  export interface RFBOptions {
    credentials?: { username?: string; password?: string; target?: string }
    shared?: boolean
    repeaterID?: string
    wsProtocols?: string[]
  }

  export default class RFB {
    constructor(target: HTMLElement, url: string, options?: RFBOptions)
    viewOnly: boolean
    scaleViewport: boolean
    resizeSession: boolean
    showDotCursor: boolean
    background: string
    qualityLevel: number
    compressionLevel: number
    capabilities: { power?: boolean }
    disconnect(): void
    sendCredentials(creds: { username?: string; password?: string; target?: string }): void
    sendCtrlAltDel(): void
    machineShutdown(): void
    machineReboot(): void
    machineReset(): void
    clipboardPasteFrom(text: string): void
    focus(): void
    blur(): void
    addEventListener(event: string, handler: (e: unknown) => void): void
    removeEventListener(event: string, handler: (e: unknown) => void): void
  }
}
