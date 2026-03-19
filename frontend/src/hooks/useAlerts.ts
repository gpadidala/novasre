import { useQuery } from '@tanstack/react-query'
import { getAlerts, getAlertGroups, type ListAlertsParams } from '@/lib/api'

export const alertKeys = {
  all: ['alerts'] as const,
  lists: () => [...alertKeys.all, 'list'] as const,
  list: (params: ListAlertsParams) => [...alertKeys.lists(), params] as const,
  groups: () => [...alertKeys.all, 'groups'] as const,
}

export function useAlerts(params?: ListAlertsParams) {
  return useQuery({
    queryKey: alertKeys.list(params ?? {}),
    queryFn: () => getAlerts(params),
    refetchInterval: 10000,
    staleTime: 5000,
  })
}

export function useFiringAlerts() {
  return useQuery({
    queryKey: alertKeys.list({ status: 'firing' }),
    queryFn: () => getAlerts({ status: 'firing' }),
    refetchInterval: 10000,
    staleTime: 5000,
  })
}

export function useAlertGroups() {
  return useQuery({
    queryKey: alertKeys.groups(),
    queryFn: getAlertGroups,
    refetchInterval: 10000,
    staleTime: 5000,
  })
}
