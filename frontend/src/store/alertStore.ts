import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type { Alert, AlertGroup } from '@/lib/api'

interface AlertState {
  alerts: Alert[]
  alertGroups: AlertGroup[]
  suppressedCount: number
  isLoading: boolean

  // Actions
  setAlerts: (alerts: Alert[]) => void
  addAlert: (alert: Alert) => void
  updateAlert: (id: string, updates: Partial<Alert>) => void
  setAlertGroups: (groups: AlertGroup[]) => void
  addAlertGroup: (group: AlertGroup) => void
  updateAlertGroup: (id: string, updates: Partial<AlertGroup>) => void
  setLoading: (loading: boolean) => void
}

export const useAlertStore = create<AlertState>()(
  devtools(
    (set, _get) => ({
      alerts: [],
      alertGroups: [],
      suppressedCount: 0,
      isLoading: false,

      setAlerts: (alerts) => {
        const suppressed = alerts.filter((a) => a.status === 'suppressed').length
        set({ alerts, suppressedCount: suppressed })
      },

      addAlert: (alert) =>
        set((state) => {
          const exists = state.alerts.some((a) => a.fingerprint === alert.fingerprint)
          if (exists) {
            return {
              alerts: state.alerts.map((a) =>
                a.fingerprint === alert.fingerprint ? { ...a, ...alert } : a
              ),
            }
          }
          return { alerts: [alert, ...state.alerts] }
        }),

      updateAlert: (id, updates) =>
        set((state) => ({
          alerts: state.alerts.map((a) =>
            a.id === id ? { ...a, ...updates } : a
          ),
        })),

      setAlertGroups: (groups) => {
        const suppressed = groups.reduce((sum, g) => sum + g.suppressed_count, 0)
        set({ alertGroups: groups, suppressedCount: suppressed })
      },

      addAlertGroup: (group) =>
        set((state) => {
          const exists = state.alertGroups.some((g) => g.id === group.id)
          if (exists) {
            return {
              alertGroups: state.alertGroups.map((g) =>
                g.id === group.id ? { ...g, ...group } : g
              ),
            }
          }
          return { alertGroups: [group, ...state.alertGroups] }
        }),

      updateAlertGroup: (id, updates) =>
        set((state) => ({
          alertGroups: state.alertGroups.map((g) =>
            g.id === id ? { ...g, ...updates } : g
          ),
        })),

      setLoading: (loading) => set({ isLoading: loading }),
    }),
    { name: 'AlertStore' }
  )
)

// Selectors
export const selectFiringCount = (state: AlertState) =>
  state.alerts.filter((a) => a.status === 'firing').length

export const selectFiringAlerts = (state: AlertState) =>
  state.alerts.filter((a) => a.status === 'firing')
