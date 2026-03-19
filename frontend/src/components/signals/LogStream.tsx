import { useState, useMemo } from 'react'
import { Search, Terminal, AlertCircle, Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { format } from 'date-fns'

export interface LogLine {
  timestamp: string
  level: 'ERROR' | 'WARN' | 'INFO' | 'DEBUG' | 'FATAL' | string
  message: string
  labels?: Record<string, string>
  stream?: string
}

interface LogStreamProps {
  logs: LogLine[]
  maxHeight?: number
  showSearch?: boolean
  title?: string
}

function getLevelStyle(level: string): string {
  const l = level.toUpperCase()
  if (l === 'ERROR' || l === 'FATAL') return 'text-red-400 bg-red-500/10 border border-red-500/20'
  if (l === 'WARN' || l === 'WARNING') return 'text-yellow-400 bg-yellow-500/10 border border-yellow-500/20'
  if (l === 'INFO') return 'text-blue-400 bg-blue-500/10 border border-blue-500/20'
  if (l === 'DEBUG') return 'text-gray-500 bg-gray-800 border border-gray-700'
  return 'text-gray-400 bg-gray-800 border border-gray-700'
}

function getLevelIcon(level: string) {
  const l = level.toUpperCase()
  if (l === 'ERROR' || l === 'FATAL') return <AlertCircle size={11} className="text-red-400" />
  if (l === 'WARN' || l === 'WARNING') return <AlertCircle size={11} className="text-yellow-400" />
  return <Info size={11} className="text-blue-400" />
}

function getRowBg(level: string): string {
  const l = level.toUpperCase()
  if (l === 'ERROR' || l === 'FATAL') return 'bg-red-500/5 hover:bg-red-500/10'
  if (l === 'WARN' || l === 'WARNING') return 'bg-yellow-500/5 hover:bg-yellow-500/10'
  return 'hover:bg-gray-800/50'
}

export function LogStream({ logs, maxHeight = 400, showSearch = true, title }: LogStreamProps) {
  const [search, setSearch] = useState('')
  const [levelFilter, setLevelFilter] = useState<string>('all')

  const levels = useMemo(() => {
    const s = new Set(logs.map((l) => l.level.toUpperCase()))
    return ['all', ...Array.from(s)]
  }, [logs])

  const filteredLogs = useMemo(() => {
    let result = logs

    if (levelFilter !== 'all') {
      result = result.filter((l) => l.level.toUpperCase() === levelFilter)
    }

    if (search.trim()) {
      const q = search.trim().toLowerCase()
      result = result.filter(
        (l) =>
          l.message.toLowerCase().includes(q) ||
          Object.values(l.labels ?? {}).some((v) => v.toLowerCase().includes(q))
      )
    }

    return result
  }, [logs, levelFilter, search])

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-800 bg-gray-950">
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-yellow-400" />
          <span className="text-xs font-semibold text-yellow-400 uppercase tracking-wide">
            {title ?? 'Log Stream'}
          </span>
          <span className="text-xs text-gray-600">({filteredLogs.length} lines)</span>
        </div>

        {showSearch && (
          <div className="flex items-center gap-2">
            {/* Level filter */}
            <div className="flex items-center gap-0.5">
              {levels.map((lvl) => (
                <button
                  key={lvl}
                  onClick={() => setLevelFilter(lvl)}
                  className={cn(
                    'px-2 py-0.5 rounded text-xs font-medium transition-colors',
                    levelFilter === lvl
                      ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                      : 'text-gray-500 hover:text-gray-300'
                  )}
                >
                  {lvl}
                </button>
              ))}
            </div>

            {/* Search */}
            <div className="relative">
              <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter logs..."
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 pl-6 text-xs text-gray-200 placeholder:text-gray-600 outline-none focus:border-yellow-500/50 w-36"
              />
            </div>
          </div>
        )}
      </div>

      {/* Log lines */}
      <div
        className="overflow-y-auto font-mono text-xs"
        style={{ maxHeight }}
      >
        {filteredLogs.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-gray-600">
            No log lines match your filters
          </div>
        ) : (
          filteredLogs.map((log, idx) => (
            <div
              key={idx}
              className={cn(
                'flex items-start gap-2 px-3 py-1 border-b border-gray-800/50 transition-colors',
                getRowBg(log.level)
              )}
            >
              {/* Timestamp */}
              <span className="text-gray-600 shrink-0 w-20 text-[10px] pt-0.5">
                {log.timestamp
                  ? format(new Date(log.timestamp), 'HH:mm:ss.SSS')
                  : ''}
              </span>

              {/* Level badge */}
              <span className={cn('inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded shrink-0 text-[10px] font-bold', getLevelStyle(log.level))}>
                {getLevelIcon(log.level)}
                {log.level.toUpperCase().slice(0, 5)}
              </span>

              {/* Stream / labels */}
              {log.stream && (
                <span className="text-gray-600 shrink-0 text-[10px] pt-0.5 max-w-20 truncate">
                  {log.stream}
                </span>
              )}

              {/* Message */}
              <span className={cn(
                'flex-1 break-all leading-relaxed',
                log.level.toUpperCase() === 'ERROR' || log.level.toUpperCase() === 'FATAL'
                  ? 'text-red-200'
                  : log.level.toUpperCase() === 'WARN'
                  ? 'text-yellow-200'
                  : 'text-gray-300'
              )}>
                {log.message}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
