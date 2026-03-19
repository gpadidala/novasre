import axios, { type AxiosInstance } from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const apiClient: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('novasre_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('novasre_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// ============================================================
// Types
// ============================================================

export interface Incident {
  id: string
  title: string
  description: string
  severity: 'P1' | 'P2' | 'P3' | 'P4'
  status: 'open' | 'investigating' | 'resolved' | 'closed'
  affected_services: string[]
  start_time: string
  resolved_time?: string | null
  created_at: string
  updated_at: string
}

export interface Alert {
  id: string
  name: string
  fingerprint: string
  labels: Record<string, string>
  annotations: Record<string, string>
  severity: string
  status: 'firing' | 'resolved' | 'suppressed'
  source: string
  fired_at: string
  resolved_at?: string | null
  incident_id?: string | null
  correlation_group_id?: string | null
}

export interface AlertGroup {
  id: string
  alerts: Alert[]
  severity: string
  suppressed_count: number
  services: string[]
  fired_at: string
}

export interface Investigation {
  id: string
  incident_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  plan: InvestigationPlanStep[]
  findings: SignalFindings
  rca?: string | null
  confidence?: number | null
  tool_calls: ToolCall[]
  started_at: string
  completed_at?: string | null
  created_by: string
}

export interface InvestigationPlanStep {
  id: string
  description: string
  agent: string
  status: 'pending' | 'running' | 'done' | 'failed'
  question?: string
}

export interface SignalFindings {
  metrics?: Record<string, unknown> | null
  logs?: Record<string, unknown> | null
  traces?: Record<string, unknown> | null
  profiles?: Record<string, unknown> | null
  frontend?: Record<string, unknown> | null
  k8s?: Record<string, unknown> | null
}

export interface ToolCall {
  id: string
  tool_name: string
  query?: string
  result?: unknown
  error?: string
  duration_ms: number
  success: boolean
  timestamp: string
}

export interface KnowledgeDocument {
  id: string
  title: string
  content: string
  type: 'runbook' | 'postmortem' | 'incident' | 'doc'
  services: string[]
  tags: string[]
  created_at: string
}

export interface KnowledgeSearchResult {
  document: KnowledgeDocument
  score: number
  excerpt: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ============================================================
// Incident API
// ============================================================

export interface ListIncidentsParams {
  status?: string
  severity?: string
  service?: string
  page?: number
  page_size?: number
}

export async function getIncidents(params?: ListIncidentsParams): Promise<PaginatedResponse<Incident>> {
  const { data } = await apiClient.get<PaginatedResponse<Incident>>('/incidents', { params })
  return data
}

export async function getIncident(id: string): Promise<Incident> {
  const { data } = await apiClient.get<Incident>(`/incidents/${id}`)
  return data
}

export async function createIncident(payload: Partial<Incident>): Promise<Incident> {
  const { data } = await apiClient.post<Incident>('/incidents', payload)
  return data
}

export async function updateIncident(id: string, payload: Partial<Incident>): Promise<Incident> {
  const { data } = await apiClient.patch<Incident>(`/incidents/${id}`, payload)
  return data
}

// ============================================================
// Alert API
// ============================================================

export interface ListAlertsParams {
  status?: string
  service?: string
  limit?: number
}

export async function getAlerts(params?: ListAlertsParams): Promise<Alert[]> {
  const { data } = await apiClient.get<Alert[]>('/alerts', { params })
  return data
}

export async function getAlertGroups(): Promise<AlertGroup[]> {
  const { data } = await apiClient.get<AlertGroup[]>('/alerts/groups')
  return data
}

// ============================================================
// Investigation API
// ============================================================

export interface TriggerInvestigationRequest {
  query?: string
  triggered_by?: string
}

export async function getInvestigation(id: string): Promise<Investigation> {
  const { data } = await apiClient.get<Investigation>(`/investigations/${id}`)
  return data
}

export async function getIncidentInvestigations(incidentId: string): Promise<Investigation[]> {
  const { data } = await apiClient.get<Investigation[]>(`/incidents/${incidentId}/investigations`)
  return data
}

export async function triggerInvestigation(
  incidentId: string,
  payload: TriggerInvestigationRequest
): Promise<Investigation> {
  const { data } = await apiClient.post<Investigation>(
    `/incidents/${incidentId}/investigate`,
    payload
  )
  return data
}

// ============================================================
// Knowledge API
// ============================================================

export interface IngestKnowledgeRequest {
  title: string
  content: string
  type: 'runbook' | 'postmortem' | 'doc'
  services?: string[]
  tags?: string[]
}

export async function searchKnowledge(query: string, top_k = 10): Promise<KnowledgeSearchResult[]> {
  const { data } = await apiClient.get<KnowledgeSearchResult[]>('/knowledge/search', {
    params: { query, top_k },
  })
  return data
}

export async function ingestKnowledge(payload: IngestKnowledgeRequest): Promise<KnowledgeDocument> {
  const { data } = await apiClient.post<KnowledgeDocument>('/knowledge/ingest', payload)
  return data
}

export async function listKnowledgeDocs(params?: { type?: string; service?: string }): Promise<KnowledgeDocument[]> {
  const { data } = await apiClient.get<KnowledgeDocument[]>('/knowledge', { params })
  return data
}

// ============================================================
// Chat API
// ============================================================

export interface ChatMessage {
  session_id: string
  content: string
  incident_id?: string
}

export async function sendChatMessage(sessionId: string, message: string, incidentId?: string): Promise<void> {
  await apiClient.post('/chat/message', {
    session_id: sessionId,
    content: message,
    incident_id: incidentId,
  })
}

// ============================================================
// Health API
// ============================================================

export interface HealthStatus {
  status: string
  db: string
  redis: string
  version?: string
}

export async function getHealth(): Promise<HealthStatus> {
  const { data } = await axios.get<HealthStatus>(`${BASE_URL}/health`)
  return data
}

export default apiClient

export { BASE_URL }
