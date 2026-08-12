declare module '@novnc/novnc' {
  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: Record<string, unknown>)
    disconnect(): void
    viewOnly: boolean
    scaleViewport: boolean
  }
}
