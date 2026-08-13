declare module "@novnc/novnc" {
  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: Record<string, unknown>)
    disconnect(): void
    viewOnly: boolean
    scaleViewport: boolean
    resizeSession: boolean
    /** Sends text to the remote session's clipboard — a real, native
     * noVNC method (core/rfb.js), not a custom addition. */
    clipboardPasteFrom(text: string): void
  }
}
