import { useNavigate } from '@tanstack/react-router'
import { Clock, Server, Search, ChevronRight } from 'lucide-react'
import { cn, getSeverityBg, getSeverityBorder, getStatusBg, formatDuration, formatRelativeTime } from '@/lib/utils'
import { useTriggerInvestigation } from '@/hooks/useIncidents'
import type { Incident } from '@/lib/api'

interface IncidentCardProps {
  incident: Incident
  compact?: boolean
}

export function IncidentCard({ incident, compact = false }: IncidentCardProps) {
  const navigate = useNavigate()
  const triggerInvestigation = useTriggerInvestigation()

  const handleInvestigate = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const inv = await triggerInvestigation.mutateAsync({
      incidentId: incident.id,
      data: { triggered_by: 'user' },
    })
    void navigate({ to: '/incidents/$id/investigation', params: { id: incident.id }, search: { investigationId: inv.id } })
  }

  const handleClick = () => {
    void navigate({ to: '/incidents/$id/investigation', params: { id: incident.id } })
  }

  return (
    <div
      onClick={handleClick}
      className={cn(
        'group relative bg-gray-900 border border-gray-800 rounded-lg cursor-pointer',
        'hover:border-gray-600 hover:bg-gray-850 transition-all duration-150',
        'border-l-4',
        getSeverityBorder(incident.severity),
        compact ? 'p-3' : 'p-4'
      )}
    >
      {/* P1 pulsing ring */}
      {incident.severity === 'P1' && incident.status !== 'resolved' && incident.status !== 'closed' && (
        <span className="absolute top-2 right-2 flex h-2.5 w-2.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
        </span>
      )}

      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* Header row */}
          <div className="flex items-center gap-2 mb-1.5">
            <span className={cn('inline-flex items-center px-2 py-0.5 rounded text-xs font-bold', getSeverityBg(incident.severity))}>
              {incident.severity}
            </span>
            <span className={cn('inline-flex items-center px-2 py-0.5 rounded text-xs font-medium', getStatusBg(incident.status))}>
              {incident.status}
            </span>
          </div>

          {/* Title */}
          <h3 className={cn('font-semibold text-gray-100 truncate group-hover:text-white', compact ? 'text-sm' : 'text-base')}>
            {incident.title}
          </h3>

          {!compact && incident.description && (
            <p className="text-sm text-gray-400 mt-0.5 line-clamp-2">{incident.description}</p>
          )}

          {/* Metadata row */}
          <div className="flex flex-wrap items-center gap-3 mt-2">
            {/* Services */}
            {incident.affected_services.length > 0 && (
              <div className="flex items-center gap-1">
                <Server size={12} className="text-gray-500" />
                <div className="flex gap-1">
                  {incident.affected_services.slice(0, 3).map((svc) => (
                    <span key={svc} className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 text-xs">
                      {svc}
                    </span>
                  ))}
                  {incident.affected_services.length > 3 && (
                    <span className="text-xs text-gray-500">+{incident.affected_services.length - 3}</span>
                  )}
                </div>
              </div>
            )}

            {/* Duration */}
            <div className="flex items-center gap-1 text-xs text-gray-500">
              <Clock size={12} />
              <span>
                {incident.status === 'resolved' || incident.status === 'closed'
                  ? `Resolved in ${formatDuration(incident.start_time, incident.resolved_time)}`
                  : `Open ${formatRelativeTime(incident.start_time)}`}
              </span>
            </div>
          </div>
        </div>

        {/* Actions */}
        {!compact && (
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleInvestigate}
              disabled={triggerInvestigation.isPending}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
                'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30',
                'hover:bg-indigo-600/40 hover:text-indigo-200',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              <Search size={12} />
              {triggerInvestigation.isPending ? 'Starting...' : 'Investigate'}
            </button>
            <ChevronRight size={16} className="text-gray-600 group-hover:text-gray-400 transition-colors" />
          </div>
        )}
      </div>
    </div>
  )
}
