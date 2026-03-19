import { useState, useEffect } from 'react'
import { Settings, CheckCircle2, XCircle, Loader2, ExternalLink, Eye, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getHealth } from '@/lib/api'

interface IntegrationConfig {
  name: string
  description: string
  envVar: string
  url?: string
  docsUrl: string
  color: string
}

const INTEGRATIONS: IntegrationConfig[] = [
  {
    name: 'Mimir',
    description: 'Prometheus-compatible long-term metrics storage (PromQL)',
    envVar: 'MIMIR_URL',
    docsUrl: 'https://grafana.com/docs/mimir/',
    color: 'text-purple-400',
  },
  {
    name: 'Loki',
    description: 'Log aggregation and querying (LogQL)',
    envVar: 'LOKI_URL',
    docsUrl: 'https://grafana.com/docs/loki/',
    color: 'text-yellow-400',
  },
  {
    name: 'Tempo',
    description: 'Distributed tracing (TraceQL)',
    envVar: 'TEMPO_URL',
    docsUrl: 'https://grafana.com/docs/tempo/',
    color: 'text-cyan-400',
  },
  {
    name: 'Pyroscope',
    description: 'Continuous profiling — CPU, memory, goroutines',
    envVar: 'PYROSCOPE_URL',
    docsUrl: 'https://grafana.com/docs/pyroscope/',
    color: 'text-orange-400',
  },
  {
    name: 'Faro',
    description: 'Real User Monitoring — Web Vitals, JS errors',
    envVar: 'FARO_COLLECTOR_URL',
    docsUrl: 'https://grafana.com/docs/grafana-cloud/monitor-applications/frontend-observability/',
    color: 'text-pink-400',
  },
  {
    name: 'Grafana',
    description: 'Dashboards, alerts, OnCall, annotations',
    envVar: 'GRAFANA_URL',
    docsUrl: 'https://grafana.com/docs/',
    color: 'text-indigo-400',
  },
  {
    name: 'OpenAI',
    description: 'LLM backend — GPT-4o primary, GPT-4o-mini for fast tasks',
    envVar: 'OPENAI_API_KEY',
    docsUrl: 'https://platform.openai.com/docs/',
    color: 'text-green-400',
  },
  {
    name: 'PostgreSQL',
    description: 'Primary relational store for incidents, alerts, investigations',
    envVar: 'DATABASE_URL',
    docsUrl: 'https://www.postgresql.org/docs/',
    color: 'text-blue-400',
  },
  {
    name: 'Redis',
    description: 'Caching, pub/sub for WebSocket fanout, rate limiting',
    envVar: 'REDIS_URL',
    docsUrl: 'https://redis.io/docs/',
    color: 'text-red-400',
  },
  {
    name: 'ChromaDB',
    description: 'Vector store for RAPTOR knowledge base embeddings',
    envVar: 'CHROMA_HOST',
    docsUrl: 'https://docs.trychroma.com/',
    color: 'text-green-400',
  },
]

interface HealthStatus {
  status: string
  db: string
  redis: string
}

function IntegrationCard({ config }: { config: IntegrationConfig }) {
  return (
    <div className="flex items-start gap-4 p-4 bg-gray-900 border border-gray-800 rounded-xl">
      <div className={cn('mt-0.5 w-2 h-2 rounded-full shrink-0 bg-current', config.color)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={cn('text-sm font-semibold', config.color)}>{config.name}</span>
          <span className="text-xs font-mono text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">
            {config.envVar}
          </span>
        </div>
        <p className="text-xs text-gray-500 mt-0.5">{config.description}</p>
      </div>
      <a
        href={config.docsUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-300 transition-colors shrink-0"
      >
        <ExternalLink size={12} />
        Docs
      </a>
    </div>
  )
}

function EnvVarRow({ label, value, secret }: { label: string; value: string; secret?: boolean }) {
  const [visible, setVisible] = useState(false)
  const displayValue = secret && !visible ? '••••••••••••' : value

  return (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-gray-800 last:border-0">
      <span className="text-xs font-mono text-gray-500 shrink-0 w-48">{label}</span>
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span className={cn('text-xs font-mono truncate flex-1', value ? 'text-green-400' : 'text-gray-600')}>
          {value ? displayValue : 'Not configured'}
        </span>
        {secret && value && (
          <button
            onClick={() => setVisible(!visible)}
            className="text-gray-600 hover:text-gray-400 shrink-0"
          >
            {visible ? <EyeOff size={12} /> : <Eye size={12} />}
          </button>
        )}
        {value ? (
          <CheckCircle2 size={13} className="text-green-400 shrink-0" />
        ) : (
          <XCircle size={13} className="text-red-400 shrink-0" />
        )}
      </div>
    </div>
  )
}

export function SettingsPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [healthLoading, setHealthLoading] = useState(true)

  useEffect(() => {
    setHealthLoading(true)
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null))
      .finally(() => setHealthLoading(false))
  }, [])

  const envVars = [
    { label: 'VITE_API_URL', value: import.meta.env.VITE_API_URL ?? 'http://localhost:8000' },
    { label: 'VITE_WS_URL', value: import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000' },
  ]

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
          <Settings size={20} className="text-gray-400" />
          Settings
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">Integration configuration and system health</p>
      </div>

      {/* System health */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-200 mb-4">System Health</h2>
        {healthLoading ? (
          <div className="flex items-center gap-2 text-gray-500">
            <Loader2 size={15} className="animate-spin" />
            <span className="text-sm">Checking health...</span>
          </div>
        ) : health ? (
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'API Server', value: health.status === 'ok' },
              { label: 'Database', value: health.db === 'ok' },
              { label: 'Redis', value: health.redis === 'ok' },
            ].map((item) => (
              <div key={item.label} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700">
                {item.value ? (
                  <CheckCircle2 size={14} className="text-green-400" />
                ) : (
                  <XCircle size={14} className="text-red-400" />
                )}
                <span className="text-sm text-gray-300">{item.label}</span>
                <span className={cn('ml-auto text-xs font-semibold', item.value ? 'text-green-400' : 'text-red-400')}>
                  {item.value ? 'OK' : 'DOWN'}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-red-400">
            <XCircle size={15} />
            <span className="text-sm">Backend unreachable. Is the server running?</span>
          </div>
        )}
      </div>

      {/* Frontend config */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-200 mb-4">Frontend Configuration</h2>
        <div>
          {envVars.map((v) => (
            <EnvVarRow key={v.label} label={v.label} value={v.value} />
          ))}
        </div>
        <p className="text-xs text-gray-600 mt-3">
          Set these variables in your <code className="text-gray-500">.env</code> or <code className="text-gray-500">.env.local</code> file.
        </p>
      </div>

      {/* Integrations */}
      <div>
        <h2 className="text-sm font-semibold text-gray-200 mb-3">Observability Integrations</h2>
        <p className="text-xs text-gray-500 mb-4">
          Configure these integrations in the backend <code className="text-gray-400">.env</code> file.
          All URLs and API keys are read server-side for security.
        </p>
        <div className="grid gap-3">
          {INTEGRATIONS.map((config) => (
            <IntegrationCard key={config.name} config={config} />
          ))}
        </div>
      </div>

      {/* Version info */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-200 mb-4">About NovaSRE</h2>
        <div className="space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-gray-600">Frontend Version</span>
            <span className="text-gray-400 font-mono">0.1.0</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">Backend Version</span>
            <span className="text-gray-400 font-mono">{health?.['version' as keyof HealthStatus] ?? 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">React</span>
            <span className="text-gray-400 font-mono">18.3</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">LangGraph</span>
            <span className="text-gray-400 font-mono">0.2+</span>
          </div>
        </div>
      </div>
    </div>
  )
}
