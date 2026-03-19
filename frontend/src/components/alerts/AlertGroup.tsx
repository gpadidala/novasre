import { useState } from 'react'
import { ChevronDown, ChevronRight, Bell, Server, Search } from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'
import { cn, getSeverityBg, formatRelativeTime } from '@/lib/utils'
import { useTriggerInvestigation } from '@/hooks/useIncidents'
import { useCreateIncident } from '@/hooks/useIncidents'
import type { AlertGroup as AlertGroupType } from '@/lib/api'

interface AlertGroupProps {
  group: AlertGroupType
}

export function AlertGroup({ group }: AlertGroupProps) {
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()
  const triggerInvestigation = useTriggerInvestigation()
  const createIncident = useCreateIncident()

  const isP1 = group.severity === 'critical' || group.severity === 'P1'

  const handleInvestigate = async (e: React.MouseEvent) => {
    e.stopPropagation()
    // Create incident first then trigger investigation
    const incident = await createIncident.mutateAsync({
      title: `Alert group: ${group.alerts[0]?.name ?? 'Unknown'}`,
      severity: (group.severity?.toUpperCase() as 'P1' | 'P2' | 'P3' | 'P4') ?? 'P2',
      status: 'open',
      affected_services: group.services,
      start_time: group.fired_at,
    })
    const inv = await triggerInvestigation.mutateAsync({
      incidentId: incident.id,
      data: { triggered_by: 'user' },
    })
    void navigate({ to: '/incidents/$id/investigation', params: { id: incident.id }, search: { investigationId: inv.id } })
  }

  const severityColor = {
    critical: 'border-l-red-500',
    high: 'border-l-orange-500',
    warning: 'border-l-yellow-500',
    info: 'border-l-blue-500',
    P1: 'border-l-red-500',
    P2: 'border-l-orange-500',
    P3: 'border-l-yellow-500',
    P4: 'border-l-blue-500',
  }[group.severity] ?? 'border-l-gray-500'

  return (
    <div
      className={cn(
        'bg-gray-900 border border-gray-800 rounded-lg overflow-hidden border-l-4',
        severityColor,
        isP1 && 'shadow-[0_0_0_1px_rgba(239,68,68,0.15)]'
      )}
    >
      {/* Group header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-800/50 transition-colors text-left"
      >
        {/* P1 pulse */}
        {isP1 && (
          <span className="flex h-2.5 w-2.5 shrink-0">
            <span className="animate-ping absolute inline-flex h-2.5 w-2.5 rounded-full bg-red-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
          </span>
        )}

        <Bell size={14} className="text-gray-400 shrink-0" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-100 truncate">
              {group.alerts[0]?.name ?? 'Alert Group'}
            </span>
            <span className={cn(
              'inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold',
              getSeverityBg(
                (['P1','P2','P3','P4'].includes(group.severity?.toUpperCase())
                  ? group.severity?.toUpperCase()
                  : group.severity === 'critical' ? 'P1'
                  : group.severity === 'high' ? 'P2'
                  : group.severity === 'warning' ? 'P3' : 'P4') as 'P1'|'P2'|'P3'|'P4'
              )
            )}>
              {group.alerts.length} alert{group.alerts.length !== 1 ? 's' : ''}
            </span>
            {group.suppressed_count > 0 && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs text-gray-500 bg-gray-800 border border-gray-700">
                {group.suppressed_count} suppressed
              </span>
            )}
          </div>

          {group.services.length > 0 && (
            <div className="flex items-center gap-1 mt-0.5">
              <Server size={11} className="text-gray-600" />
              <span className="text-xs text-gray-500">
                {group.services.slice(0, 3).join(', ')}
                {group.services.length > 3 && ` +${group.services.length - 3} more`}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-gray-500">{formatRelativeTime(group.fired_at)}</span>
          <button
            onClick={handleInvestigate}
            disabled={triggerInvestigation.isPending || createIncident.isPending}
            className="flex items-center gap-1 px-2 py-1 rounded bg-indigo-600/20 border border-indigo-500/30 text-indigo-300 text-xs hover:bg-indigo-600/40 transition-colors disabled:opacity-50"
          >
            <Search size={11} />
            Investigate
          </button>
          {expanded ? <ChevronDown size={14} className="text-gray-500" /> : <ChevronRight size={14} className="text-gray-500" />}
        </div>
      </button>

      {/* Expanded alerts */}
      {expanded && (
        <div className="border-t border-gray-800 divide-y divide-gray-800/50">
          {group.alerts.map((alert) => (
            <div key={alert.id} className="px-4 py-2.5 flex items-start gap-3 hover:bg-gray-800/30">
              <div className={cn(
                'mt-0.5 w-2 h-2 rounded-full shrink-0',
                alert.status === 'firing' ? 'bg-red-400' : 'bg-gray-500'
              )} />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-200 truncate">{alert.name}</p>
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
                  {Object.entries(alert.labels).slice(0, 4).map(([k, v]) => (
                    <span key={k} className="text-xs text-gray-500">
                      <span className="text-gray-600">{k}=</span>{v}
                    </span>
                  ))}
                </div>
              </div>
              <span className="text-xs text-gray-500 shrink-0">{formatRelativeTime(alert.fired_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
