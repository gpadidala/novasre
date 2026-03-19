import { useState } from 'react'
import { Plus, AlertTriangle, Search } from 'lucide-react'
import { cn, type Severity } from '@/lib/utils'
import { IncidentFeed } from '@/components/incidents/IncidentFeed'
import { useCreateIncident } from '@/hooks/useIncidents'

const SEVERITY_OPTIONS: Severity[] = ['P1', 'P2', 'P3', 'P4']

interface CreateIncidentModalProps {
  onClose: () => void
}

function CreateIncidentModal({ onClose }: CreateIncidentModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<Severity>('P2')
  const [services, setServices] = useState('')
  const createIncident = useCreateIncident()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await createIncident.mutateAsync({
      title,
      description,
      severity,
      status: 'open',
      affected_services: services.split(',').map((s) => s.trim()).filter(Boolean),
      start_time: new Date().toISOString(),
    })
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h2 className="text-base font-semibold text-gray-100">Create Incident</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">✕</button>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="p-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Title *</label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. High error rate on checkout service"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 outline-none focus:border-indigo-500/50"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="What is happening? Impact? Initial observations?"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 outline-none focus:border-indigo-500/50 resize-none"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Severity *</label>
            <div className="flex gap-2">
              {SEVERITY_OPTIONS.map((sev) => (
                <button
                  key={sev}
                  type="button"
                  onClick={() => setSeverity(sev)}
                  className={cn(
                    'flex-1 py-1.5 rounded-lg text-sm font-bold border transition-colors',
                    severity === sev
                      ? sev === 'P1' ? 'bg-red-500/30 border-red-500 text-red-300'
                        : sev === 'P2' ? 'bg-orange-500/30 border-orange-500 text-orange-300'
                        : sev === 'P3' ? 'bg-yellow-500/30 border-yellow-500 text-yellow-300'
                        : 'bg-blue-500/30 border-blue-500 text-blue-300'
                      : 'bg-gray-800 border-gray-700 text-gray-500 hover:text-gray-300'
                  )}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Affected Services</label>
            <input
              type="text"
              value={services}
              onChange={(e) => setServices(e.target.value)}
              placeholder="checkout, payment, db (comma separated)"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 outline-none focus:border-indigo-500/50"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 rounded-lg border border-gray-700 text-sm text-gray-400 hover:text-gray-200 hover:border-gray-600 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title || createIncident.isPending}
              className="flex-1 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {createIncident.isPending ? 'Creating...' : 'Create Incident'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function IncidentsPage() {
  const [showCreate, setShowCreate] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  return (
    <div className="flex flex-col h-full gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <AlertTriangle size={20} className="text-orange-400" />
            Incidents
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Track and investigate production incidents</p>
        </div>

        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search incidents..."
              className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 pl-9 text-sm text-gray-200 placeholder:text-gray-600 outline-none focus:border-indigo-500/50 w-56"
            />
          </div>

          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <Plus size={15} />
            New Incident
          </button>
        </div>
      </div>

      {/* Feed */}
      <div className="flex-1 min-h-0">
        <IncidentFeed />
      </div>

      {/* Modal */}
      {showCreate && <CreateIncidentModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}
