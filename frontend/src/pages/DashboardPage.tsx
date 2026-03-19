import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Clock, AlertTriangle, Filter, Flame } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useIncidents } from '@/hooks/useIncidents'
import { useAlerts } from '@/hooks/useAlerts'
import { useIncidentStore } from '@/store/incidentStore'
import { useAlertStore, selectFiringCount } from '@/store/alertStore'
import { IncidentCard } from '@/components/incidents/IncidentCard'
import { AlertFeed } from '@/components/alerts/AlertFeed'
import { AgentChat } from '@/components/agent/AgentChat'

interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  icon: React.ReactNode
  color: string
}

function StatCard({ label, value, sub, icon, color }: StatCardProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex items-start gap-3">
      <div className={cn('flex items-center justify-center w-9 h-9 rounded-lg shrink-0', color)}>
        {icon}
      </div>
      <div>
        <p className="text-2xl font-bold text-gray-100">{value}</p>
        <p className="text-xs text-gray-500 mt-0.5">{label}</p>
        {sub && <p className="text-xs font-medium text-green-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

export function DashboardPage() {
  const navigate = useNavigate()

  // Fetch data
  const { data: incidentsData } = useIncidents({ status: 'open,investigating', page_size: 10 })
  const { data: allIncidentsData } = useIncidents({ page_size: 100 })
  const { data: alertsData } = useAlerts()
  const { setIncidents } = useIncidentStore()
  const firingCount = useAlertStore(selectFiringCount)

  // Sync to stores
  useEffect(() => {
    if (allIncidentsData?.items) {
      setIncidents(allIncidentsData.items, allIncidentsData.total)
    }
  }, [allIncidentsData, setIncidents])

  const activeIncidents = incidentsData?.items ?? []
  const allIncidents = allIncidentsData?.items ?? []

  // Compute stats
  const openCount = allIncidents.filter((i) => i.status === 'open' || i.status === 'investigating').length

  const resolvedToday = allIncidents.filter((i) => {
    if (!i.resolved_time) return false
    const resolvedAt = new Date(i.resolved_time)
    const now = new Date()
    return resolvedAt.toDateString() === now.toDateString()
  })

  const avgMttrMs = resolvedToday.length > 0
    ? resolvedToday.reduce((sum, i) => {
        const start = new Date(i.start_time).getTime()
        const end = new Date(i.resolved_time!).getTime()
        return sum + (end - start)
      }, 0) / resolvedToday.length
    : null

  const mttrDisplay = avgMttrMs == null ? 'N/A'
    : avgMttrMs < 60000 ? `${Math.round(avgMttrMs / 1000)}s`
    : avgMttrMs < 3600000 ? `${Math.round(avgMttrMs / 60000)}m`
    : `${(avgMttrMs / 3600000).toFixed(1)}h`

  const totalAlertsToday = alertsData?.length ?? 0
  const firingAlerts = alertsData?.filter((a) => a.status === 'firing').length ?? 0
  const suppressedAlerts = totalAlertsToday > 0
    ? Math.round(((totalAlertsToday - firingAlerts) / totalAlertsToday) * 100)
    : 0

  return (
    <div className="flex flex-col gap-6 h-full">
      {/* Page title */}
      <div>
        <h1 className="text-xl font-bold text-gray-100">Command Center</h1>
        <p className="text-sm text-gray-500 mt-0.5">Real-time incident intelligence and SRE operations</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Mean Time to Resolve"
          value={mttrDisplay}
          sub={resolvedToday.length > 0 ? `${resolvedToday.length} resolved today` : undefined}
          icon={<Clock size={18} className="text-blue-400" />}
          color="bg-blue-500/10"
        />
        <StatCard
          label="Open Incidents"
          value={openCount}
          sub={openCount > 0 ? 'Requires attention' : 'All clear!'}
          icon={<AlertTriangle size={18} className="text-orange-400" />}
          color="bg-orange-500/10"
        />
        <StatCard
          label="Alert Noise Reduction"
          value={`-${suppressedAlerts}%`}
          sub="3-layer correlation"
          icon={<Filter size={18} className="text-green-400" />}
          color="bg-green-500/10"
        />
        <StatCard
          label="Firing Alerts"
          value={firingCount}
          sub={firingCount === 0 ? 'No active alerts' : 'Needs attention'}
          icon={<Flame size={18} className="text-red-400" />}
          color="bg-red-500/10"
        />
      </div>

      {/* Main panels */}
      <div className="flex gap-6 flex-1 min-h-0">
        {/* Left: Active incidents */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
              Active Incidents
            </h2>
            <button
              onClick={() => void navigate({ to: '/incidents' })}
              className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              View all →
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
            {activeIncidents.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-gray-600 gap-2 bg-gray-900 rounded-xl border border-gray-800">
                <AlertTriangle size={28} className="text-gray-700" />
                <p className="text-sm">No active incidents</p>
              </div>
            ) : (
              activeIncidents.map((incident) => (
                <IncidentCard key={incident.id} incident={incident} />
              ))
            )}
          </div>
        </div>

        {/* Right: Alert feed */}
        <div className="w-96 flex flex-col shrink-0">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
              Live Alert Feed
            </h2>
            <button
              onClick={() => void navigate({ to: '/alerts' })}
              className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              View all →
            </button>
          </div>
          <div className="flex-1 overflow-hidden">
            <AlertFeed />
          </div>
        </div>
      </div>

      {/* Agent chat panel */}
      <div>
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">
          SRE Agent
        </h2>
        <AgentChat compact className="h-80" />
      </div>
    </div>
  )
}
