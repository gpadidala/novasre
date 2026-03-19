import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getIncidents,
  getIncident,
  createIncident,
  updateIncident,
  triggerInvestigation,
  getIncidentInvestigations,
  type ListIncidentsParams,
  type Incident,
  type TriggerInvestigationRequest,
} from '@/lib/api'

export const incidentKeys = {
  all: ['incidents'] as const,
  lists: () => [...incidentKeys.all, 'list'] as const,
  list: (params: ListIncidentsParams) => [...incidentKeys.lists(), params] as const,
  details: () => [...incidentKeys.all, 'detail'] as const,
  detail: (id: string) => [...incidentKeys.details(), id] as const,
  investigations: (id: string) => [...incidentKeys.detail(id), 'investigations'] as const,
}

export function useIncidents(params?: ListIncidentsParams) {
  return useQuery({
    queryKey: incidentKeys.list(params ?? {}),
    queryFn: () => getIncidents(params),
    refetchInterval: 15000, // refresh every 15s
    staleTime: 10000,
  })
}

export function useIncident(id: string) {
  return useQuery({
    queryKey: incidentKeys.detail(id),
    queryFn: () => getIncident(id),
    staleTime: 30000,
  })
}

export function useCreateIncident() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<Incident>) => createIncident(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: incidentKeys.lists() })
    },
  })
}

export function useUpdateIncident() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: Partial<Incident> }) =>
      updateIncident(id, updates),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: incidentKeys.detail(variables.id) })
      qc.invalidateQueries({ queryKey: incidentKeys.lists() })
    },
  })
}

export function useTriggerInvestigation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ incidentId, data }: { incidentId: string; data: TriggerInvestigationRequest }) =>
      triggerInvestigation(incidentId, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: incidentKeys.investigations(variables.incidentId) })
    },
  })
}

export function useIncidentInvestigations(incidentId: string) {
  return useQuery({
    queryKey: incidentKeys.investigations(incidentId),
    queryFn: () => getIncidentInvestigations(incidentId),
    refetchInterval: 5000, // poll while investigation may be running
  })
}
