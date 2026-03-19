import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type { InvestigationPlanStep, ToolCall } from '@/lib/api'

export interface AgentMessage {
  id: string
  type: 'user' | 'assistant' | 'thinking' | 'finding' | 'rca' | 'error'
  agent?: string
  content: string
  timestamp: string
  streaming?: boolean
}

export interface AgentSession {
  id: string
  incidentId?: string
  messages: AgentMessage[]
  toolCalls: ToolCall[]
  plan: InvestigationPlanStep[]
  status: 'idle' | 'thinking' | 'investigating' | 'done' | 'error'
  createdAt: string
}

interface AgentState {
  sessions: Record<string, AgentSession>
  activeSessionId: string | null

  // Actions
  createSession: (sessionId: string, incidentId?: string) => void
  setActiveSession: (sessionId: string | null) => void
  addMessage: (sessionId: string, message: AgentMessage) => void
  updateLastMessage: (sessionId: string, content: string) => void
  addToolCall: (sessionId: string, toolCall: ToolCall) => void
  updateToolCall: (sessionId: string, toolCallId: string, updates: Partial<ToolCall>) => void
  setInvestigationPlan: (sessionId: string, plan: InvestigationPlanStep[]) => void
  updatePlanStep: (sessionId: string, stepId: string, updates: Partial<InvestigationPlanStep>) => void
  setSessionStatus: (sessionId: string, status: AgentSession['status']) => void
  clearSession: (sessionId: string) => void
}

let messageIdCounter = 0
function nextId() {
  return `msg-${Date.now()}-${++messageIdCounter}`
}

export const useAgentStore = create<AgentState>()(
  devtools(
    (set) => ({
      sessions: {},
      activeSessionId: null,

      createSession: (sessionId, incidentId) =>
        set((state) => ({
          sessions: {
            ...state.sessions,
            [sessionId]: {
              id: sessionId,
              incidentId,
              messages: [],
              toolCalls: [],
              plan: [],
              status: 'idle',
              createdAt: new Date().toISOString(),
            },
          },
          activeSessionId: sessionId,
        })),

      setActiveSession: (sessionId) => set({ activeSessionId: sessionId }),

      addMessage: (sessionId, message) =>
        set((state) => {
          const session = state.sessions[sessionId]
          if (!session) return state
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: {
                ...session,
                messages: [...session.messages, { ...message, id: message.id || nextId() }],
              },
            },
          }
        }),

      updateLastMessage: (sessionId, content) =>
        set((state) => {
          const session = state.sessions[sessionId]
          if (!session || session.messages.length === 0) return state
          const messages = [...session.messages]
          const last = messages[messages.length - 1]
          messages[messages.length - 1] = { ...last, content, streaming: false }
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: { ...session, messages },
            },
          }
        }),

      addToolCall: (sessionId, toolCall) =>
        set((state) => {
          const session = state.sessions[sessionId]
          if (!session) return state
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: {
                ...session,
                toolCalls: [...session.toolCalls, toolCall],
              },
            },
          }
        }),

      updateToolCall: (sessionId, toolCallId, updates) =>
        set((state) => {
          const session = state.sessions[sessionId]
          if (!session) return state
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: {
                ...session,
                toolCalls: session.toolCalls.map((tc) =>
                  tc.id === toolCallId ? { ...tc, ...updates } : tc
                ),
              },
            },
          }
        }),

      setInvestigationPlan: (sessionId, plan) =>
        set((state) => {
          const session = state.sessions[sessionId]
          if (!session) return state
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: { ...session, plan },
            },
          }
        }),

      updatePlanStep: (sessionId, stepId, updates) =>
        set((state) => {
          const session = state.sessions[sessionId]
          if (!session) return state
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: {
                ...session,
                plan: session.plan.map((s) =>
                  s.id === stepId ? { ...s, ...updates } : s
                ),
              },
            },
          }
        }),

      setSessionStatus: (sessionId, status) =>
        set((state) => {
          const session = state.sessions[sessionId]
          if (!session) return state
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: { ...session, status },
            },
          }
        }),

      clearSession: (sessionId) =>
        set((state) => {
          const { [sessionId]: _removed, ...rest } = state.sessions
          return {
            sessions: rest,
            activeSessionId: state.activeSessionId === sessionId ? null : state.activeSessionId,
          }
        }),
    }),
    { name: 'AgentStore' }
  )
)
