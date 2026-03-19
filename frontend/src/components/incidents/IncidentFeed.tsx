import { useState } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useIncidents } from '@/hooks/useIncidents'
import { IncidentCard } from './IncidentCard'

type SeverityFilter = 'all' | 'P1' | 'P2' | 'P3' | 'P4'
type StatusFilter = 'active' | 'resolved' | 'all'

const severityTabs: SeverityFilter[] = ['all', 'P1', 'P2', 'P3', 'P4']

export function IncidentFeed() {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')

  const params = {
    severity: severityFilter !== 'all' ? severityFilter : undefined,
    status: statusFilter === 'active' ? 'open,investigating' : statusFilter === 'resolved' ? 'resolved,closed' : undefined,
    page_size: 50,
  }

  const { data, isLoading, isError, refetch, isFetching } = useIncidents(params)

  const incidents = data?.items ?? []

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="flex items-center justify-between gap-3 mb-4">
        {/* Severity tabs */}
        <div className="flex items-center gap-1 bg-gray-900 rounded-lg p-1 border border-gray-800">
          {severityTabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setSeverityFilter(tab)}
              className={cn(
                'px-3 py-1 rounded-md text-xs font-medium transition-colors',
                severityFilter === tab
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              )}
            >
              {tab === 'all' ? 'All' : tab}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {/* Status filter */}
          <div className="flex items-center gap-1 bg-gray-900 rounded-lg p-1 border border-gray-800">
            {(['active', 'resolved', 'all'] as StatusFilter[]).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={cn(
                  'px-3 py-1 rounded-md text-xs font-medium transition-colors capitalize',
                  statusFilter === s
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-400 hover:text-gray-200'
                )}
              >
                {s}
              </button>
            ))}
          </div>

          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
          >
            <RefreshCw size={14} className={cn(isFetching && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading && (
        <div className="flex-1 space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-24 bg-gray-900 rounded-lg border border-gray-800 animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-500 gap-3">
          <AlertTriangle size={32} className="text-red-400" />
          <p className="text-sm">Failed to load incidents</p>
          <button
            onClick={() => void refetch()}
            className="text-xs text-indigo-400 hover:text-indigo-300"
          >
            Try again
          </button>
        </div>
      )}

      {!isLoading && !isError && incidents.length === 0 && (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-500 gap-2">
          <AlertTriangle size={32} className="text-gray-600" />
          <p className="text-sm">No incidents found</p>
          <p className="text-xs text-gray-600">Matching filters: {severityFilter} / {statusFilter}</p>
        </div>
      )}

      {!isLoading && !isError && incidents.length > 0 && (
        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          {incidents.map((incident) => (
            <IncidentCard key={incident.id} incident={incident} />
          ))}
          {data && data.total > incidents.length && (
            <p className="text-xs text-center text-gray-600 py-2">
              Showing {incidents.length} of {data.total} incidents
            </p>
          )}
        </div>
      )}
    </div>
  )
}
