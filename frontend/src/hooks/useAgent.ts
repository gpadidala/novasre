import { useCallback, useEffect, useRef } from 'react'
import { useAgentStore } from '@/store/agentStore'
import { getSessionWS, destroySessionWS, type WSMessageType } from '@/lib/websocket'
import { generateSessionId } from '@/lib/utils'
import type { WSMessage } from '@/lib/websocket' // eslint-disable-line @typescript-eslint/no-unused-vars

export function useAgent(incidentId?: string) {
  const sessionIdRef = useRef<string>(generateSessionId())
  const sessionId = sessionIdRef.current

  const store = useAgentStore()
  const session = store.sessions[sessionId]

  useEffect(() => {
    // Create session in store
    store.createSession(sessionId, incidentId)

    // Set up WS and subscribe
    const ws = getSessionWS(sessionId)

    const handleMessage = (msg: WSMessage) => {
      switch (msg.type) {
        case 'thinking':
          if (msg.content && msg.content !== 'connected') {
            store.addMessage(sessionId, {
              id: `think-${Date.now()}`,
              type: 'thinking',
              agent: msg.agent,
              content: msg.content,
              timestamp: new Date().toISOString(),
            })
          }
          break

        case 'tool_call':
          store.addToolCall(sessionId, {
            id: `tc-${Date.now()}`,
            tool_name: msg.tool ?? 'unknown',
            query: msg.query,
            duration_ms: 0,
            success: true,
            timestamp: new Date().toISOString(),
          })
          store.setSessionStatus(sessionId, 'investigating')
          break

        case 'tool_result': {
          // Find most recent tool call for this tool and update
          const currentSession = useAgentStore.getState().sessions[sessionId]
          const tc = [...(currentSession?.toolCalls ?? [])].reverse().find(
            (t) => t.tool_name === msg.tool
          )
          if (tc) {
            store.updateToolCall(sessionId, tc.id, {
              result: msg.result,
              success: msg.success !== false,
              duration_ms: msg.duration_ms ?? 0,
            })
          }
          break
        }

        case 'finding':
          store.addMessage(sessionId, {
            id: `find-${Date.now()}`,
            type: 'finding',
            agent: msg.agent,
            content: msg.content ?? '',
            timestamp: new Date().toISOString(),
          })
          break

        case 'rca':
          store.addMessage(sessionId, {
            id: `rca-${Date.now()}`,
            type: 'rca',
            content: msg.content ?? '',
            timestamp: new Date().toISOString(),
          })
          store.setSessionStatus(sessionId, 'done')
          break

        case 'done':
          store.setSessionStatus(sessionId, 'done')
          break

        case 'error':
          store.addMessage(sessionId, {
            id: `err-${Date.now()}`,
            type: 'error',
            content: msg.content ?? 'An error occurred',
            timestamp: new Date().toISOString(),
          })
          store.setSessionStatus(sessionId, 'error')
          break
      }
    }

    const unsub = ws.subscribe('*' as WSMessageType, handleMessage)

    return () => {
      unsub()
      destroySessionWS(sessionId)
      store.clearSession(sessionId)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const sendMessage = useCallback(
    (content: string) => {
      const ws = getSessionWS(sessionId)

      // Add user message to store
      store.addMessage(sessionId, {
        id: `user-${Date.now()}`,
        type: 'user',
        content,
        timestamp: new Date().toISOString(),
      })

      store.setSessionStatus(sessionId, 'thinking')

      // Send over WS
      ws.send({
        type: 'message',
        content,
        session_id: sessionId,
        incident_id: incidentId,
      })
    },
    [sessionId, incidentId, store]
  )

  const clearMessages = useCallback(() => {
    store.createSession(sessionId, incidentId)
  }, [sessionId, incidentId, store])

  return {
    sessionId,
    session,
    messages: session?.messages ?? [],
    toolCalls: session?.toolCalls ?? [],
    plan: session?.plan ?? [],
    status: session?.status ?? 'idle',
    sendMessage,
    clearMessages,
  }
}
