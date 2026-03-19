import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type { Incident } from '@/lib/api'

interface IncidentState {
  incidents: Incident[]
  activeIncident: Incident | null
  isLoading: boolean
  totalCount: number

  // Actions
  setIncidents: (incidents: Incident[], total?: number) => void
  addIncident: (incident: Incident) => void
  updateIncident: (id: string, updates: Partial<Incident>) => void
  setActiveIncident: (incident: Incident | null) => void
  setLoading: (loading: boolean) => void
}

export const useIncidentStore = create<IncidentState>()(
  devtools(
    (set) => ({
      incidents: [],
      activeIncident: null,
      isLoading: false,
      totalCount: 0,

      setIncidents: (incidents, total) =>
        set({ incidents, totalCount: total ?? incidents.length }),

      addIncident: (incident) =>
        set((state) => {
          const exists = state.incidents.some((i) => i.id === incident.id)
          if (exists) return state
          return {
            incidents: [incident, ...state.incidents],
            totalCount: state.totalCount + 1,
          }
        }),

      updateIncident: (id, updates) =>
        set((state) => ({
          incidents: state.incidents.map((i) =>
            i.id === id ? { ...i, ...updates } : i
          ),
          activeIncident:
            state.activeIncident?.id === id
              ? { ...state.activeIncident, ...updates }
              : state.activeIncident,
        })),

      setActiveIncident: (incident) => set({ activeIncident: incident }),

      setLoading: (loading) => set({ isLoading: loading }),
    }),
    { name: 'IncidentStore' }
  )
)

// Selectors
export const selectP1Count = (state: IncidentState) =>
  state.incidents.filter((i) => i.severity === 'P1' && i.status !== 'resolved' && i.status !== 'closed').length

export const selectOpenIncidents = (state: IncidentState) =>
  state.incidents.filter((i) => i.status === 'open' || i.status === 'investigating')
