import { useEffect, useRef, useState, useCallback } from 'react'
import { WebSocketManager, type WSMessage, type WSMessageType } from '@/lib/websocket'

interface UseWebSocketOptions {
  autoConnect?: boolean
  onMessage?: (msg: WSMessage) => void
}

export function useWebSocket(path: string, options: UseWebSocketOptions = {}) {
  const { autoConnect = true, onMessage } = options
  const [connectionState, setConnectionState] = useState<'connected' | 'connecting' | 'disconnected'>('disconnected')
  const managerRef = useRef<WebSocketManager | null>(null)

  useEffect(() => {
    const manager = new WebSocketManager()
    managerRef.current = manager

    // Subscribe to all messages to update connection state
    const unsubAll = manager.subscribe('*' as WSMessageType, (msg) => {
      setConnectionState(manager.connectionState)
      onMessage?.(msg)
    })

    if (autoConnect) {
      manager.connect(path)
    }

    // Poll connection state
    const interval = setInterval(() => {
      setConnectionState(manager.connectionState)
    }, 1000)

    return () => {
      unsubAll()
      clearInterval(interval)
      manager.disconnect()
    }
  }, [path, autoConnect]) // eslint-disable-line react-hooks/exhaustive-deps

  const connect = useCallback(() => {
    managerRef.current?.connect(path)
  }, [path])

  const disconnect = useCallback(() => {
    managerRef.current?.disconnect()
  }, [])

  const send = useCallback((data: Record<string, unknown>) => {
    managerRef.current?.send(data)
  }, [])

  const subscribe = useCallback((type: WSMessageType | '*', handler: (msg: WSMessage) => void) => {
    return managerRef.current?.subscribe(type, handler) ?? (() => {})
  }, [])

  return { connectionState, connect, disconnect, send, subscribe, manager: managerRef.current }
}

// Simpler hook for just subscribing to a shared manager
export function useWSSubscription(
  manager: WebSocketManager | null,
  type: WSMessageType | '*',
  handler: (msg: WSMessage) => void
) {
  useEffect(() => {
    if (!manager) return
    const unsub = manager.subscribe(type, handler)
    return unsub
  }, [manager, type, handler])
}
