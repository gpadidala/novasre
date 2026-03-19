import { useState, useEffect } from 'react'
import { Bell, RefreshCw, Filter, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAlerts, useAlertGroups } from '@/hooks/useAlerts'
import { useAlertStore } from '@/store/alertStore'
import { AlertGroup } from './AlertGroup'

type ViewMode = 'grouped' | 'raw'

export function AlertFeed() {
  const [viewMode, setViewMode] = useState<ViewMode>('grouped')
  const [showSuppressed, setShowSuppressed] = useState(false)

  const { data: rawAlerts, refetch: refetchAlerts, isFetching: isFetchingAlerts } = useAlerts()
  const { data: groups, refetch: refetchGroups, isFetching: isFetchingGroups } = useAlertGroups()
  const { setAlerts, setAlertGroups, suppressedCount } = useAlertStore()

  // Sync to store
  useEffect(() => {
    if (rawAlerts) setAlerts(rawAlerts)
  }, [rawAlerts, setAlerts])

  useEffect(() => {
    if (groups) setAlertGroups(groups)
  }, [groups, setAlertGroups])

  const isFetching = isFetchingAlerts || isFetchingGroups

  const handleRefresh = () => {
    void refetchAlerts()
    void refetchGroups()
  }

  const firingAlerts = rawAlerts?.filter((a) => a.status === 'firing') ?? []
  const suppressedAlerts = rawAlerts?.filter((a) => a.status === 'suppressed') ?? []
  const displayedAlerts = showSuppressed ? rawAlerts ?? [] : firingAlerts

  const displayedGroups = groups ?? []

  return (
    <div className="flex flex-col h-full">
      {/* Header controls */}
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-1 bg-gray-900 rounded-lg p-1 border border-gray-800">
          {(['grouped', 'raw'] as ViewMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={cn(
                'px-3 py-1 rounded-md text-xs font-medium transition-colors capitalize',
                viewMode === mode ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:text-gray-200'
              )}
            >
              {mode}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {suppressedCount > 0 && (
            <button
              onClick={() => setShowSuppressed(!showSuppressed)}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs transition-colors',
                showSuppressed
                  ? 'bg-gray-700 border-gray-600 text-gray-200'
                  : 'bg-gray-900 border-gray-800 text-gray-500 hover:text-gray-300'
              )}
            >
              <EyeOff size={12} />
              {suppressedCount} suppressed
            </button>
          )}
          <button
            onClick={handleRefresh}
            disabled={isFetching}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
          >
            <RefreshCw size={14} className={cn(isFetching && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* Summary bar */}
      <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 mb-3 text-xs">
        <span className="flex items-center gap-1.5 text-red-400">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
          {firingAlerts.length} firing
        </span>
        <span className="text-gray-700">|</span>
        <span className="text-gray-500">{suppressedAlerts.length} suppressed</span>
        {suppressedCount > 0 && (
          <>
            <span className="text-gray-700">|</span>
            <span className="flex items-center gap-1 text-green-500">
              <Filter size={11} />
              {suppressedCount} noise-reduced
            </span>
          </>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-0.5">
        {viewMode === 'grouped' ? (
          displayedGroups.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-600 gap-2">
              <Bell size={28} />
              <p className="text-sm">No alert groups</p>
            </div>
          ) : (
            displayedGroups.map((group) => (
              <AlertGroup key={group.id} group={group} />
            ))
          )
        ) : (
          displayedAlerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-600 gap-2">
              <Bell size={28} />
              <p className="text-sm">No {showSuppressed ? '' : 'firing '}alerts</p>
            </div>
          ) : (
            displayedAlerts.map((alert) => (
              <div
                key={alert.id}
                className={cn(
                  'flex items-start gap-3 px-3 py-2 rounded-lg bg-gray-900 border border-gray-800',
                  alert.status === 'firing' && 'border-l-2 border-l-red-500'
                )}
              >
                <div className={cn(
                  'mt-1 w-2 h-2 rounded-full shrink-0',
                  alert.status === 'firing' ? 'bg-red-500 animate-pulse' : 'bg-gray-500'
                )} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-200">{alert.name}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {Object.entries(alert.labels)
                      .slice(0, 3)
                      .map(([k, v]) => `${k}="${v}"`)
                      .join(', ')}
                  </p>
                </div>
                <span className={cn(
                  'text-xs px-1.5 py-0.5 rounded shrink-0',
                  alert.status === 'firing'
                    ? 'text-red-400 bg-red-500/10'
                    : 'text-gray-500 bg-gray-800'
                )}>
                  {alert.status}
                </span>
              </div>
            ))
          )
        )}
      </div>
    </div>
  )
}
