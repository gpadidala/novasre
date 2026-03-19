import { Bell, Wifi, WifiOff, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useIncidentStore, selectP1Count } from '@/store/incidentStore'
import { useAlertStore, selectFiringCount } from '@/store/alertStore'
import { useEffect, useState } from 'react'
import { getHealth } from '@/lib/api'

type ConnStatus = 'connected' | 'connecting' | 'disconnected'

function ConnectionIndicator({ status }: { status: ConnStatus }) {
  return (
    <div className="flex items-center gap-1.5">
      {status === 'connected' && (
        <>
          <Wifi size={14} className="text-green-400" />
          <span className="text-xs text-green-400">Live</span>
        </>
      )}
      {status === 'connecting' && (
        <>
          <Loader2 size={14} className="text-yellow-400 animate-spin" />
          <span className="text-xs text-yellow-400">Connecting</span>
        </>
      )}
      {status === 'disconnected' && (
        <>
          <WifiOff size={14} className="text-red-400" />
          <span className="text-xs text-red-400">Offline</span>
        </>
      )}
    </div>
  )
}

export function TopBar() {
  const p1Count = useIncidentStore(selectP1Count)
  const firingCount = useAlertStore(selectFiringCount)
  const [connStatus, setConnStatus] = useState<ConnStatus>('disconnected')

  useEffect(() => {
    let mounted = true

    async function checkHealth() {
      try {
        await getHealth()
        if (mounted) setConnStatus('connected')
      } catch {
        if (mounted) setConnStatus('disconnected')
      }
    }

    setConnStatus('connecting')
    void checkHealth()

    const interval = setInterval(() => void checkHealth(), 30000)
    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])

  return (
    <header className="flex items-center justify-between px-6 h-14 bg-gray-900 border-b border-gray-800 shrink-0">
      {/* Left: breadcrumb / title area - rendered by page if needed */}
      <div className="flex items-center gap-4">
        <h1 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Command Center
        </h1>
      </div>

      {/* Right: status badges */}
      <div className="flex items-center gap-4">
        {p1Count > 0 && (
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-red-500/20 border border-red-500/30">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="text-xs font-semibold text-red-400">
              {p1Count} Active P1{p1Count !== 1 ? 's' : ''}
            </span>
          </div>
        )}

        {firingCount > 0 && (
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-orange-500/20 border border-orange-500/30">
            <Bell size={12} className={cn('text-orange-400', firingCount > 0 && 'animate-pulse')} />
            <span className="text-xs font-semibold text-orange-400">
              {firingCount} Firing
            </span>
          </div>
        )}

        <div className="h-4 w-px bg-gray-700" />
        <ConnectionIndicator status={connStatus} />
      </div>
    </header>
  )
}
