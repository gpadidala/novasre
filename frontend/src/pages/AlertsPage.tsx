import { useEffect } from 'react'
import { Bell, TrendingDown } from 'lucide-react'
import { useAlerts, useAlertGroups } from '@/hooks/useAlerts'
import { useAlertStore, selectFiringCount } from '@/store/alertStore'
import { AlertFeed } from '@/components/alerts/AlertFeed'

export function AlertsPage() {
  const { data: alerts } = useAlerts()
  const { data: groups } = useAlertGroups()
  const { setAlerts, setAlertGroups, suppressedCount } = useAlertStore()
  const firingCount = useAlertStore(selectFiringCount)

  useEffect(() => {
    if (alerts) setAlerts(alerts)
  }, [alerts, setAlerts])

  useEffect(() => {
    if (groups) setAlertGroups(groups)
  }, [groups, setAlertGroups])

  const totalAlerts = alerts?.length ?? 0
  const noiseReduction = totalAlerts > 0
    ? Math.round(((totalAlerts - firingCount) / totalAlerts) * 100)
    : 0

  return (
    <div className="flex flex-col h-full gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Bell size={20} className="text-orange-400" />
            Alert Correlation
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            3-layer correlation: temporal + topological + semantic
          </p>
        </div>

        {/* Noise reduction badge */}
        {noiseReduction > 0 && (
          <div className="flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/20 rounded-xl">
            <TrendingDown size={16} className="text-green-400" />
            <div>
              <p className="text-sm font-bold text-green-400">-{noiseReduction}% noise</p>
              <p className="text-xs text-gray-500">{suppressedCount} alerts suppressed</p>
            </div>
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-red-400">{firingCount}</p>
          <p className="text-xs text-gray-500 mt-1">Firing</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-gray-400">{suppressedCount}</p>
          <p className="text-xs text-gray-500 mt-1">Suppressed</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-indigo-400">{groups?.length ?? 0}</p>
          <p className="text-xs text-gray-500 mt-1">Alert Groups</p>
        </div>
      </div>

      {/* Alert feed */}
      <div className="flex-1 min-h-0">
        <AlertFeed />
      </div>
    </div>
  )
}
