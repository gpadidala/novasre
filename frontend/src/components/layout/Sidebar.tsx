import { Link, useRouterState } from '@tanstack/react-router'
import {
  LayoutDashboard,
  AlertTriangle,
  Bell,
  BookOpen,
  Settings,
  Zap,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useIncidentStore, selectP1Count } from '@/store/incidentStore'

interface NavItem {
  to: string
  label: string
  icon: React.ReactNode
  badge?: number
}

function NavItemRow({ item }: { item: NavItem }) {
  const routerState = useRouterState()
  const isActive =
    item.to === '/'
      ? routerState.location.pathname === '/'
      : routerState.location.pathname.startsWith(item.to)

  return (
    <Link
      to={item.to}
      className={cn(
        'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
        isActive
          ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
          : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800 border border-transparent'
      )}
    >
      <span className="shrink-0">{item.icon}</span>
      <span className="flex-1">{item.label}</span>
      {item.badge != null && item.badge > 0 && (
        <span className="flex items-center justify-center min-w-5 h-5 px-1.5 rounded-full bg-red-500 text-white text-xs font-bold">
          {item.badge > 99 ? '99+' : item.badge}
        </span>
      )}
    </Link>
  )
}

export function Sidebar() {
  const p1Count = useIncidentStore(selectP1Count)

  const navItems: NavItem[] = [
    {
      to: '/',
      label: 'Dashboard',
      icon: <LayoutDashboard size={18} />,
    },
    {
      to: '/incidents',
      label: 'Incidents',
      icon: <AlertTriangle size={18} />,
      badge: p1Count,
    },
    {
      to: '/alerts',
      label: 'Alerts',
      icon: <Bell size={18} />,
    },
    {
      to: '/knowledge',
      label: 'Knowledge Base',
      icon: <BookOpen size={18} />,
    },
    {
      to: '/settings',
      label: 'Settings',
      icon: <Settings size={18} />,
    },
  ]

  return (
    <aside className="flex flex-col w-60 h-screen bg-gray-900 border-r border-gray-800 shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-gray-800">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-600">
          <Zap size={16} className="text-white" />
        </div>
        <div>
          <span className="text-base font-bold text-gray-100 tracking-tight">NovaSRE</span>
          <p className="text-[10px] text-gray-500 -mt-0.5">Intelligent O11y Agent</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => (
          <NavItemRow key={item.to} item={item} />
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-800">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-xs text-gray-500">All systems operational</span>
        </div>
      </div>
    </aside>
  )
}
