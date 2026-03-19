import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, Bot, User, Loader2, Cpu, AlertTriangle, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAgent } from '@/hooks/useAgent'
import { ToolCallCard } from './ToolCallCard'
import type { AgentMessage } from '@/store/agentStore'

interface AgentChatProps {
  incidentId?: string
  className?: string
  compact?: boolean
}

const SUGGESTIONS = [
  'What is the root cause of this incident?',
  'Show me the error rate for the last 30 minutes',
  'Are there any slow traces in the checkout service?',
  'What do the logs say about this error?',
  'Compare current CPU usage with yesterday',
]

function MessageBubble({ message }: { message: AgentMessage }) {
  const isUser = message.type === 'user'
  const isRCA = message.type === 'rca'
  const isError = message.type === 'error'

  if (isUser) {
    return (
      <div className="flex items-start gap-2 justify-end">
        <div className="max-w-[80%] px-3 py-2 rounded-xl bg-indigo-600/30 border border-indigo-500/30 text-sm text-gray-100">
          {message.content}
        </div>
        <div className="flex items-center justify-center w-7 h-7 rounded-full bg-gray-700 shrink-0 mt-0.5">
          <User size={14} className="text-gray-300" />
        </div>
      </div>
    )
  }

  if (message.type === 'thinking') {
    return (
      <div className="flex items-start gap-2">
        <div className="flex items-center justify-center w-7 h-7 rounded-full bg-indigo-600/20 border border-indigo-500/30 shrink-0 mt-0.5">
          <Cpu size={12} className="text-indigo-400" />
        </div>
        <div className="px-3 py-1.5 rounded-xl bg-gray-900 border border-gray-800 text-xs text-gray-500 italic flex items-center gap-2">
          {message.agent && (
            <span className="text-indigo-400 font-semibold not-italic">[{message.agent}]</span>
          )}
          {message.content}
          {message.streaming && (
            <span className="inline-flex gap-0.5">
              <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1 h-1 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </span>
          )}
        </div>
      </div>
    )
  }

  if (message.type === 'finding') {
    return (
      <div className="flex items-start gap-2">
        <div className="flex items-center justify-center w-7 h-7 rounded-full bg-yellow-600/20 border border-yellow-500/30 shrink-0 mt-0.5">
          <FileText size={12} className="text-yellow-400" />
        </div>
        <div className="flex-1 max-w-[90%] px-3 py-2 rounded-xl bg-yellow-500/5 border border-yellow-500/20">
          {message.agent && (
            <p className="text-xs font-semibold text-yellow-400 mb-1 capitalize">{message.agent} findings</p>
          )}
          <p className="text-sm text-gray-300">{message.content}</p>
        </div>
      </div>
    )
  }

  if (isRCA) {
    return (
      <div className="flex items-start gap-2">
        <div className="flex items-center justify-center w-7 h-7 rounded-full bg-green-600/20 border border-green-500/30 shrink-0 mt-0.5">
          <Bot size={12} className="text-green-400" />
        </div>
        <div className="flex-1 px-4 py-3 rounded-xl bg-green-500/5 border border-green-500/20">
          <p className="text-xs font-semibold text-green-400 mb-2 uppercase tracking-wide">Root Cause Analysis</p>
          <div className="prose prose-sm prose-invert max-w-none text-gray-200">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h2: ({ children }) => <h2 className="text-base font-bold text-gray-100 mt-3 mb-1">{children}</h2>,
                h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-200 mt-2 mb-1">{children}</h3>,
                p: ({ children }) => <p className="text-sm text-gray-300 mb-2">{children}</p>,
                ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 mb-2 text-sm text-gray-300">{children}</ul>,
                li: ({ children }) => <li className="text-sm text-gray-300">{children}</li>,
                code: ({ children }) => <code className="px-1 py-0.5 rounded bg-gray-800 text-xs font-mono text-yellow-300">{children}</code>,
                strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-start gap-2">
        <div className="flex items-center justify-center w-7 h-7 rounded-full bg-red-600/20 border border-red-500/30 shrink-0 mt-0.5">
          <AlertTriangle size={12} className="text-red-400" />
        </div>
        <div className="px-3 py-2 rounded-xl bg-red-500/5 border border-red-500/20 text-sm text-red-300">
          {message.content}
        </div>
      </div>
    )
  }

  // Default assistant message
  return (
    <div className="flex items-start gap-2">
      <div className="flex items-center justify-center w-7 h-7 rounded-full bg-indigo-600/20 border border-indigo-500/30 shrink-0 mt-0.5">
        <Bot size={12} className="text-indigo-400" />
      </div>
      <div className="flex-1 max-w-[90%] px-3 py-2 rounded-xl bg-gray-900 border border-gray-800">
        <div className="prose prose-sm prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        </div>
        {message.streaming && (
          <span className="inline-block w-1.5 h-4 bg-indigo-400 animate-pulse ml-0.5 align-middle" />
        )}
      </div>
    </div>
  )
}

export function AgentChat({ incidentId, className, compact = false }: AgentChatProps) {
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const { messages, toolCalls, status, sendMessage } = useAgent(incidentId)

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolCalls])

  // Cmd+K focus shortcut
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || status === 'thinking' || status === 'investigating') return
    sendMessage(trimmed)
    setInput('')
  }, [input, status, sendMessage])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit]
  )

  const isProcessing = status === 'thinking' || status === 'investigating'

  // Build combined timeline: messages + tool calls
  const timeline = [
    ...messages.map((m) => ({ kind: 'message' as const, ts: m.timestamp, data: m })),
    ...toolCalls.map((tc) => ({ kind: 'tool' as const, ts: tc.timestamp, data: tc })),
  ].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime())

  return (
    <div className={cn('flex flex-col bg-gray-900 rounded-xl border border-gray-800', className)}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-800">
        <Bot size={16} className="text-indigo-400" />
        <span className="text-sm font-semibold text-gray-200">SRE Agent</span>
        {isProcessing && (
          <span className="flex items-center gap-1.5 ml-auto text-xs text-yellow-400">
            <Loader2 size={12} className="animate-spin" />
            {status === 'thinking' ? 'Planning investigation...' : 'Investigating...'}
          </span>
        )}
        {status === 'done' && (
          <span className="ml-auto text-xs text-green-400">Investigation complete</span>
        )}
      </div>

      {/* Messages area */}
      <div className={cn('flex-1 overflow-y-auto p-4 space-y-3', compact ? 'max-h-64' : 'min-h-0')}>
        {timeline.length === 0 && (
          <div className="space-y-3">
            <div className="flex items-start gap-2">
              <div className="flex items-center justify-center w-7 h-7 rounded-full bg-indigo-600/20 border border-indigo-500/30 shrink-0">
                <Bot size={12} className="text-indigo-400" />
              </div>
              <div className="px-3 py-2 rounded-xl bg-gray-900 border border-gray-800 text-sm text-gray-300">
                Hi! I'm your SRE agent. Ask me to investigate incidents, query metrics, check logs, or analyze traces.
                {incidentId && (
                  <span className="block mt-1 text-xs text-gray-500">
                    I'll focus my investigation on incident <code className="text-indigo-400">{incidentId.slice(0, 8)}</code>.
                  </span>
                )}
              </div>
            </div>

            {!compact && (
              <div className="flex flex-wrap gap-2 pl-9">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => { setInput(s); inputRef.current?.focus() }}
                    className="text-xs px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-500 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {timeline.map((item, idx) => {
          if (item.kind === 'message') {
            return <MessageBubble key={`msg-${idx}`} message={item.data} />
          }
          return (
            <div key={`tool-${idx}`} className="pl-9">
              <ToolCallCard toolCall={item.data} index={toolCalls.indexOf(item.data)} />
            </div>
          )
        })}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-gray-800 p-3">
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={incidentId ? "Ask about this incident... (⌘+Enter to send)" : "Ask me anything... (⌘+Enter to send)"}
              rows={2}
              className={cn(
                'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100',
                'placeholder:text-gray-600 resize-none outline-none',
                'focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20',
                'disabled:opacity-50'
              )}
              disabled={isProcessing}
            />
          </div>
          <button
            onClick={handleSubmit}
            disabled={!input.trim() || isProcessing}
            className={cn(
              'flex items-center justify-center w-9 h-9 rounded-lg transition-colors shrink-0',
              'bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {isProcessing ? (
              <Loader2 size={15} className="text-white animate-spin" />
            ) : (
              <Send size={15} className="text-white" />
            )}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-1.5 text-right">⌘K to focus · ⌘↵ to send</p>
      </div>
    </div>
  )
}
