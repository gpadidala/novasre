import { useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Clock } from 'lucide-react'
import { cn, getSignalColor } from '@/lib/utils'
import type { ToolCall } from '@/lib/api'

interface ToolCallCardProps {
  toolCall: ToolCall
  index?: number
}

function formatResult(result: unknown): string {
  if (result == null) return 'No result'
  if (typeof result === 'string') return result
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
  }
}

export function ToolCallCard({ toolCall, index }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const colorClass = getSignalColor(toolCall.tool_name)

  return (
    <div className={cn('rounded-lg border bg-gray-950 overflow-hidden', colorClass.split(' ').find(c => c.startsWith('border')) ?? 'border-gray-700')}>
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-900 transition-colors text-left"
      >
        {/* Index */}
        {index != null && (
          <span className="text-xs text-gray-600 font-mono w-5 shrink-0">#{index + 1}</span>
        )}

        {/* Tool name badge */}
        <span className={cn('inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-semibold border', colorClass)}>
          {toolCall.tool_name}
        </span>

        {/* Query preview */}
        {toolCall.query && (
          <span className="flex-1 text-xs text-gray-400 truncate font-mono">
            {toolCall.query}
          </span>
        )}

        {/* Status */}
        <div className="flex items-center gap-2 shrink-0">
          {toolCall.duration_ms > 0 && (
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <Clock size={10} />
              {toolCall.duration_ms < 1000
                ? `${Math.round(toolCall.duration_ms)}ms`
                : `${(toolCall.duration_ms / 1000).toFixed(1)}s`}
            </span>
          )}

          {toolCall.success ? (
            <CheckCircle2 size={14} className="text-green-400" />
          ) : toolCall.error ? (
            <XCircle size={14} className="text-red-400" />
          ) : (
            <span className="w-3.5 h-3.5 rounded-full border-2 border-yellow-400 border-t-transparent animate-spin" />
          )}

          {expanded ? (
            <ChevronDown size={14} className="text-gray-500" />
          ) : (
            <ChevronRight size={14} className="text-gray-500" />
          )}
        </div>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t border-gray-800 px-3 py-2 space-y-2">
          {toolCall.query && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Query</p>
              <pre className="text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-x-auto font-mono whitespace-pre-wrap break-all">
                {toolCall.query}
              </pre>
            </div>
          )}

          {toolCall.error && (
            <div>
              <p className="text-xs font-semibold text-red-400 uppercase mb-1">Error</p>
              <pre className="text-xs text-red-300 bg-red-900/20 rounded p-2 overflow-x-auto font-mono whitespace-pre-wrap break-all">
                {toolCall.error}
              </pre>
            </div>
          )}

          {toolCall.result != null && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Result</p>
              <pre className="text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-x-auto font-mono whitespace-pre-wrap break-all max-h-48">
                {formatResult(toolCall.result)}
              </pre>
            </div>
          )}

          {!toolCall.result && !toolCall.error && (
            <div className="flex items-center gap-2 text-xs text-yellow-400">
              <span className="w-3 h-3 rounded-full border-2 border-yellow-400 border-t-transparent animate-spin" />
              Running...
            </div>
          )}
        </div>
      )}
    </div>
  )
}
