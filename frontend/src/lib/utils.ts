import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { formatDistanceToNow, format, differenceInSeconds, differenceInMinutes, differenceInHours } from 'date-fns'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatRelativeTime(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return formatDistanceToNow(d, { addSuffix: true })
}

export function formatDateTime(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return format(d, 'MMM d, yyyy HH:mm:ss')
}

export function formatDuration(startDate: string | Date, endDate?: string | Date | null): string {
  const start = typeof startDate === 'string' ? new Date(startDate) : startDate
  const end = endDate ? (typeof endDate === 'string' ? new Date(endDate) : endDate) : new Date()

  const totalSeconds = differenceInSeconds(end, start)

  if (totalSeconds < 60) return `${totalSeconds}s`

  const minutes = differenceInMinutes(end, start)
  if (minutes < 60) return `${minutes}m`

  const hours = differenceInHours(end, start)
  const remainingMinutes = minutes - hours * 60
  if (hours < 24) return `${hours}h ${remainingMinutes}m`

  const days = Math.floor(hours / 24)
  const remainingHours = hours - days * 24
  return `${days}d ${remainingHours}h`
}

export type Severity = 'P1' | 'P2' | 'P3' | 'P4'
export type Status = 'open' | 'investigating' | 'resolved' | 'closed'
export type AlertStatus = 'firing' | 'resolved' | 'suppressed'

export function getSeverityColor(severity: Severity): string {
  switch (severity) {
    case 'P1': return 'text-red-500'
    case 'P2': return 'text-orange-500'
    case 'P3': return 'text-yellow-500'
    case 'P4': return 'text-blue-500'
    default: return 'text-gray-400'
  }
}

export function getSeverityBg(severity: Severity): string {
  switch (severity) {
    case 'P1': return 'bg-red-500/20 text-red-400 border border-red-500/30'
    case 'P2': return 'bg-orange-500/20 text-orange-400 border border-orange-500/30'
    case 'P3': return 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
    case 'P4': return 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
    default: return 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
  }
}

export function getSeverityBorder(severity: Severity): string {
  switch (severity) {
    case 'P1': return 'border-l-red-500'
    case 'P2': return 'border-l-orange-500'
    case 'P3': return 'border-l-yellow-500'
    case 'P4': return 'border-l-blue-500'
    default: return 'border-l-gray-500'
  }
}

export function getStatusColor(status: Status | AlertStatus): string {
  switch (status) {
    case 'open': return 'text-red-400'
    case 'investigating': return 'text-yellow-400'
    case 'resolved': return 'text-green-400'
    case 'closed': return 'text-gray-400'
    case 'firing': return 'text-red-400'
    case 'suppressed': return 'text-gray-400'
    default: return 'text-gray-400'
  }
}

export function getStatusBg(status: Status | AlertStatus): string {
  switch (status) {
    case 'open': return 'bg-red-500/20 text-red-400 border border-red-500/30'
    case 'investigating': return 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
    case 'resolved': return 'bg-green-500/20 text-green-400 border border-green-500/30'
    case 'closed': return 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
    case 'firing': return 'bg-red-500/20 text-red-400 border border-red-500/30'
    case 'suppressed': return 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
    default: return 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
  }
}

export function getSignalColor(signal: string): string {
  switch (signal.toLowerCase()) {
    case 'mimir':
    case 'metrics':
    case 'mimir_query':
    case 'mimir_query_range':
    case 'mimir_label_values':
      return 'text-purple-400 bg-purple-500/10 border-purple-500/30'
    case 'loki':
    case 'logs':
    case 'loki_query_range':
    case 'loki_extract_errors':
      return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30'
    case 'tempo':
    case 'traces':
    case 'tempo_search':
    case 'tempo_get_trace':
    case 'tempo_slow_traces':
      return 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30'
    case 'pyroscope':
    case 'profiles':
    case 'pyroscope_query':
    case 'pyroscope_diff':
      return 'text-orange-400 bg-orange-500/10 border-orange-500/30'
    case 'faro':
    case 'frontend':
    case 'faro_web_vitals':
    case 'faro_errors':
    case 'faro_sessions':
      return 'text-pink-400 bg-pink-500/10 border-pink-500/30'
    case 'grafana':
    case 'grafana_alerts':
    case 'grafana_annotations':
      return 'text-indigo-400 bg-indigo-500/10 border-indigo-500/30'
    default:
      return 'text-gray-400 bg-gray-500/10 border-gray-500/30'
  }
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str
  return str.slice(0, maxLen - 3) + '...'
}

export function generateSessionId(): string {
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}
