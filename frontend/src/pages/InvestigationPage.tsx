import { useState, useEffect } from 'react'
import { useParams, useSearch, useNavigate } from '@tanstack/react-router'
import {
  Brain,
  ChevronLeft,
  RefreshCw,
  CheckCircle2,
  Clock,
  Activity,
  FileText,
  Terminal,
  GitBranch,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn, getSeverityBg, getStatusBg, formatDuration, formatRelativeTime } from '@/lib/utils'
import { useIncident, useIncidentInvestigations, useTriggerInvestigation } from '@/hooks/useIncidents'
import { InvestigationPlan } from '@/components/agent/InvestigationPlan'
import { ToolCallCard } from '@/components/agent/ToolCallCard'
import { MetricsChart, type MetricDataPoint } from '@/components/signals/MetricsChart'
import { LogStream, type LogLine } from '@/components/signals/LogStream'
import { TraceWaterfall, type TraceSpan } from '@/components/signals/TraceWaterfall'
import { AgentChat } from '@/components/agent/AgentChat'
import type { Investigation, ToolCall, InvestigationPlanStep } from '@/lib/api'

type SignalTab = 'metrics' | 'logs' | 'traces'

function SignalPanel({ investigation }: { investigation: Investigation | null }) {
  const [activeTab, setActiveTab] = useState<SignalTab>('metrics')

  // Extract mock signal data from findings
  const metricsData: MetricDataPoint[] = []
  const logLines: LogLine[] = []
  const traceSpans: TraceSpan[] = []

  // Parse findings if available
  if (investigation?.findings?.metrics) {
    const mf = investigation.findings.metrics as Record<string, unknown>
    if (Array.isArray(mf.datapoints)) {
      const dp = mf.datapoints as Array<{ ts: number; er?: number; rr?: number; p99?: number }>
      dp.forEach((d) => {
        metricsData.push({
          timestamp: d.ts,
          error_rate: d.er,
          request_rate: d.rr,
          duration_p99: d.p99,
        })
      })
    }
  }

  if (investigation?.findings?.logs) {
    const lf = investigation.findings.logs as Record<string, unknown>
    if (Array.isArray(lf.lines)) {
      const lines = lf.lines as Array<{ ts: string; level: string; msg: string; stream?: string }>
      lines.forEach((l) => {
        logLines.push({ timestamp: l.ts, level: l.level, message: l.msg, stream: l.stream })
      })
    }
  }

  if (investigation?.findings?.traces) {
    const tf = investigation.findings.traces as Record<string, unknown>
    if (Array.isArray(tf.spans)) {
      const spans = tf.spans as Array<{
        spanId: string
        parentSpanId?: string
        operationName: string
        serviceName: string
        startTime: number
        duration: number
        status: 'ok' | 'error' | 'unset'
        tags?: Record<string, string>
      }>
      traceSpans.push(...spans)
    }
  }

  const tabs: { id: SignalTab; label: string; icon: React.ReactNode; color: string }[] = [
    { id: 'metrics', label: 'Metrics', icon: <Activity size={13} />, color: 'text-purple-400' },
    { id: 'logs', label: 'Logs', icon: <Terminal size={13} />, color: 'text-yellow-400' },
    { id: 'traces', label: 'Traces', icon: <GitBranch size={13} />, color: 'text-cyan-400' },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Tabs */}
      <div className="flex items-center gap-1 mb-3">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border',
              activeTab === tab.id
                ? `${tab.color} bg-gray-800 border-gray-600`
                : 'text-gray-500 border-transparent hover:text-gray-300 hover:bg-gray-800'
            )}
          >
            {tab.icon}
            {tab.label}
            {investigation?.findings?.[tab.id as keyof typeof investigation.findings] && (
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
            )}
          </button>
        ))}
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'metrics' && (
          <MetricsChart
            data={metricsData}
            title="RED Metrics — Error Rate · Request Rate · P99 Latency"
            height={280}
            showAnomaly
          />
        )}

        {activeTab === 'logs' && (
          <LogStream
            logs={logLines}
            maxHeight={400}
            title="Log Stream (Loki)"
          />
        )}

        {activeTab === 'traces' && (
          <TraceWaterfall
            spans={traceSpans}
            title="Trace Waterfall (Tempo)"
          />
        )}

        {/* RCA Report */}
        {investigation?.rca && (
          <div className="mt-4 bg-green-500/5 border border-green-500/20 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle2 size={16} className="text-green-400" />
              <span className="text-sm font-semibold text-green-400">Root Cause Analysis</span>
              {investigation.confidence != null && (
                <span className="ml-auto text-xs text-gray-500">
                  Confidence: <span className="text-green-400 font-semibold">{Math.round(investigation.confidence * 100)}%</span>
                </span>
              )}
            </div>
            <div className="prose prose-sm prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h2: ({ children }) => <h2 className="text-sm font-bold text-gray-100 mt-3 mb-1.5 border-b border-gray-800 pb-1">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-xs font-semibold text-gray-200 mt-2 mb-1">{children}</h3>,
                  p: ({ children }) => <p className="text-sm text-gray-300 mb-2">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 mb-2 text-sm text-gray-300">{children}</ul>,
                  li: ({ children }) => <li className="text-sm text-gray-300">{children}</li>,
                  code: ({ children }) => <code className="px-1 py-0.5 rounded bg-gray-800 text-xs font-mono text-yellow-300">{children}</code>,
                  strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
                }}
              >
                {investigation.rca}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export function InvestigationPage() {
  const params = useParams({ strict: false }) as Record<string, string>
  const incidentId = params.id ?? ''
  const search = useSearch({ strict: false }) as Record<string, string>
  const investigationId = search.investigationId
  const navigate = useNavigate()
  const triggerInvestigation = useTriggerInvestigation()

  const { data: incident, isLoading: incidentLoading } = useIncident(incidentId)
  const { data: investigations, isLoading: invLoading, refetch } = useIncidentInvestigations(incidentId)

  // Active investigation — prefer explicit investigationId from URL, else latest
  const activeInvestigation: Investigation | null =
    investigations?.find((inv) => inv.id === investigationId) ??
    investigations?.[0] ??
    null

  const isRunning = activeInvestigation?.status === 'running' || activeInvestigation?.status === 'pending'

  // Auto-refresh while running
  useEffect(() => {
    if (!isRunning) return
    const interval = setInterval(() => void refetch(), 3000)
    return () => clearInterval(interval)
  }, [isRunning, refetch])

  const handleTrigger = async () => {
    await triggerInvestigation.mutateAsync({
      incidentId,
      data: { triggered_by: 'user' },
    })
    void refetch()
  }

  if (incidentLoading || invLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500 gap-3">
        <RefreshCw size={20} className="animate-spin" />
        <span>Loading investigation...</span>
      </div>
    )
  }

  if (!incident) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-500 gap-3">
        <Brain size={32} />
        <p>Incident not found</p>
      </div>
    )
  }

  // Map investigation data to plan steps
  const planSteps: InvestigationPlanStep[] = activeInvestigation?.plan ?? []
  const toolCalls: ToolCall[] = activeInvestigation?.tool_calls ?? []

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <button
            onClick={() => { void navigate({ to: '/incidents' }) }}
            className="mt-1 p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          >
            <ChevronLeft size={18} />
          </button>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={cn('inline-flex items-center px-2 py-0.5 rounded text-xs font-bold', getSeverityBg(incident.severity))}>
                {incident.severity}
              </span>
              <span className={cn('inline-flex items-center px-2 py-0.5 rounded text-xs font-medium', getStatusBg(incident.status))}>
                {incident.status}
              </span>
              <span className="text-xs text-gray-600">
                Started {formatRelativeTime(incident.start_time)}
                {incident.resolved_time && ` · Resolved in ${formatDuration(incident.start_time, incident.resolved_time)}`}
              </span>
            </div>
            <h1 className="text-lg font-bold text-gray-100">{incident.title}</h1>
            {incident.affected_services.length > 0 && (
              <div className="flex items-center gap-1 mt-1">
                {incident.affected_services.map((svc) => (
                  <span key={svc} className="px-2 py-0.5 rounded bg-gray-800 text-xs text-gray-400 border border-gray-700">
                    {svc}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {activeInvestigation && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-xs">
              {activeInvestigation.status === 'running' || activeInvestigation.status === 'pending' ? (
                <>
                  <RefreshCw size={12} className="text-yellow-400 animate-spin" />
                  <span className="text-yellow-400">Investigating</span>
                </>
              ) : activeInvestigation.status === 'completed' ? (
                <>
                  <CheckCircle2 size={12} className="text-green-400" />
                  <span className="text-green-400">Completed</span>
                </>
              ) : (
                <>
                  <span className="w-2 h-2 rounded-full bg-red-400" />
                  <span className="text-red-400">Failed</span>
                </>
              )}
            </div>
          )}

          {!activeInvestigation && (
            <button
              onClick={() => void handleTrigger()}
              disabled={triggerInvestigation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
            >
              <Brain size={15} />
              {triggerInvestigation.isPending ? 'Starting...' : 'Start Investigation'}
            </button>
          )}

          <button
            onClick={() => void refetch()}
            className="p-2 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          >
            <RefreshCw size={15} className={cn(isRunning && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* Main layout */}
      <div className="flex gap-5 flex-1 min-h-0">
        {/* Left column: plan + tool calls */}
        <div className="w-80 shrink-0 flex flex-col gap-4 min-h-0 overflow-y-auto">
          {/* Investigation plan */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Brain size={15} className="text-indigo-400" />
              <h3 className="text-sm font-semibold text-gray-200">Investigation Plan</h3>
            </div>
            <InvestigationPlan steps={planSteps} />
          </div>

          {/* Tool calls */}
          {toolCalls.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <FileText size={15} className="text-gray-400" />
                <h3 className="text-sm font-semibold text-gray-200">Tool Calls</h3>
                <span className="text-xs text-gray-600 ml-auto">{toolCalls.length}</span>
              </div>
              <div className="space-y-2">
                {toolCalls.map((tc, idx) => (
                  <ToolCallCard key={tc.id} toolCall={tc} index={idx} />
                ))}
              </div>
            </div>
          )}

          {/* Timing info */}
          {activeInvestigation && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2 mb-2">
                <Clock size={14} className="text-gray-500" />
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Timeline</h3>
              </div>
              <div className="text-xs space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-gray-600">Started</span>
                  <span className="text-gray-400">{formatRelativeTime(activeInvestigation.started_at)}</span>
                </div>
                {activeInvestigation.completed_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">Completed</span>
                    <span className="text-gray-400">{formatRelativeTime(activeInvestigation.completed_at)}</span>
                  </div>
                )}
                {activeInvestigation.completed_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">Duration</span>
                    <span className="text-green-400 font-semibold">
                      {formatDuration(activeInvestigation.started_at, activeInvestigation.completed_at)}
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-gray-600">Triggered by</span>
                  <span className="text-gray-400">{activeInvestigation.created_by}</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right column: signal evidence + RCA */}
        <div className="flex-1 flex flex-col gap-4 min-h-0">
          {/* No investigation yet */}
          {!activeInvestigation && (
            <div className="flex-1 flex flex-col items-center justify-center bg-gray-900 border border-gray-800 rounded-xl text-gray-600 gap-3">
              <Brain size={40} className="text-gray-700" />
              <p className="text-base font-medium text-gray-400">No investigation yet</p>
              <p className="text-sm">Start an investigation to see signal evidence and RCA</p>
              <button
                onClick={() => void handleTrigger()}
                disabled={triggerInvestigation.isPending}
                className="mt-2 flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
              >
                <Brain size={16} />
                Start Investigation
              </button>
            </div>
          )}

          {/* Signal panels */}
          {activeInvestigation && (
            <div className="flex-1 min-h-0">
              <SignalPanel investigation={activeInvestigation} />
            </div>
          )}

          {/* Agent chat anchored to this incident */}
          <AgentChat
            incidentId={incidentId}
            className="h-64 shrink-0"
          />
        </div>
      </div>
    </div>
  )
}
