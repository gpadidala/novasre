const BASE_WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'

export type WSMessageType =
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'finding'
  | 'rca'
  | 'done'
  | 'error'
  | 'alert'
  | 'alert_group'
  | 'incident_update'
  | 'investigation_update'

export interface WSMessage {
  type: WSMessageType
  agent?: string
  tool?: string
  query?: string
  result?: unknown
  content?: string
  session_id?: string
  incident_id?: string
  duration_ms?: number
  success?: boolean
  data?: unknown
}

export type MessageHandler = (message: WSMessage) => void

class WebSocketManager {
  private ws: WebSocket | null = null
  private url: string = ''
  private handlers: Map<WSMessageType | '*', Set<MessageHandler>> = new Map()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private baseDelay = 1000 // 1s
  private maxDelay = 30000 // 30s
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private manualClose = false
  private isConnecting = false

  connect(urlOrPath: string): void {
    if (this.isConnecting || this.ws?.readyState === WebSocket.OPEN) return

    this.manualClose = false
    // Accept either a full ws:// URL or a relative path
    this.url = urlOrPath.startsWith('ws') ? urlOrPath : `${BASE_WS_URL}${urlOrPath}`
    this._doConnect()
  }

  private _doConnect(): void {
    this.isConnecting = true

    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        this.isConnecting = false
        this.reconnectAttempts = 0
        console.debug('[WS] Connected to', this.url)
        this._emit('*' as WSMessageType, { type: 'thinking', content: 'connected' })
      }

      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const message = JSON.parse(event.data as string) as WSMessage
          this._emit(message.type, message)
          this._emit('*' as WSMessageType, message)
        } catch {
          console.warn('[WS] Failed to parse message:', event.data)
        }
      }

      this.ws.onerror = (event) => {
        this.isConnecting = false
        console.warn('[WS] Error', event)
      }

      this.ws.onclose = () => {
        this.isConnecting = false
        this.ws = null

        if (!this.manualClose && this.reconnectAttempts < this.maxReconnectAttempts) {
          const delay = Math.min(
            this.baseDelay * Math.pow(2, this.reconnectAttempts),
            this.maxDelay
          )
          this.reconnectAttempts++
          console.debug(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`)
          this.reconnectTimer = setTimeout(() => this._doConnect(), delay)
        }
      }
    } catch (err) {
      this.isConnecting = false
      console.error('[WS] Failed to connect:', err)
    }
  }

  disconnect(): void {
    this.manualClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    } else {
      console.warn('[WS] Cannot send — not connected')
    }
  }

  subscribe(type: WSMessageType | '*', handler: MessageHandler): () => void {
    const key = type as WSMessageType
    if (!this.handlers.has(key)) {
      this.handlers.set(key, new Set())
    }
    this.handlers.get(key)!.add(handler)

    return () => {
      this.handlers.get(key)?.delete(handler)
    }
  }

  private _emit(type: WSMessageType, message: WSMessage): void {
    this.handlers.get(type)?.forEach((h) => h(message))
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  get connectionState(): 'connected' | 'connecting' | 'disconnected' {
    if (this.ws?.readyState === WebSocket.OPEN) return 'connected'
    if (this.ws?.readyState === WebSocket.CONNECTING || this.isConnecting) return 'connecting'
    return 'disconnected'
  }
}

// Single global WS manager for the agent
export const agentWS = new WebSocketManager()

// Per-session managers (created lazily)
const sessionManagers: Map<string, WebSocketManager> = new Map()

export function getSessionWS(sessionId: string): WebSocketManager {
  if (!sessionManagers.has(sessionId)) {
    const mgr = new WebSocketManager()
    mgr.connect(`/ws/agent/${sessionId}`)
    sessionManagers.set(sessionId, mgr)
  }
  return sessionManagers.get(sessionId)!
}

export function destroySessionWS(sessionId: string): void {
  const mgr = sessionManagers.get(sessionId)
  if (mgr) {
    mgr.disconnect()
    sessionManagers.delete(sessionId)
  }
}

export { WebSocketManager }
