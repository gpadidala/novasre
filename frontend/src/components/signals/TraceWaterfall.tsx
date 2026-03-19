import { useState } from 'react'
import { ChevronRight, ChevronDown, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface TraceSpan {
  spanId: string
  parentSpanId?: string
  operationName: string
  serviceName: string
  startTime: number // ms offset from trace start
  duration: number  // ms
  status: 'ok' | 'error' | 'unset'
  tags?: Record<string, string>
  logs?: Array<{ timestamp: number; fields: Record<string, string> }>
  children?: TraceSpan[]
}

interface TraceWaterfallProps {
  spans: TraceSpan[]
  traceId?: string
  title?: string
}

// Assign unique colors per service
const SERVICE_COLORS = [
  '#22d3ee', // cyan
  '#c084fc', // purple
  '#f472b6', // pink
  '#fb923c', // orange
  '#4ade80', // green
  '#facc15', // yellow
  '#60a5fa', // blue
  '#f87171', // red
]

function buildTree(spans: TraceSpan[]): TraceSpan[] {
  const map = new Map<string, TraceSpan>()
  const roots: TraceSpan[] = []

  spans.forEach((s) => map.set(s.spanId, { ...s, children: [] }))

  map.forEach((span) => {
    if (span.parentSpanId && map.has(span.parentSpanId)) {
      map.get(span.parentSpanId)!.children!.push(span)
    } else {
      roots.push(span)
    }
  })

  return roots
}

function SpanRow({
  span,
  totalDuration,
  serviceColorMap,
  depth,
}: {
  span: TraceSpan
  totalDuration: number
  serviceColorMap: Map<string, string>
  depth: number
}) {
  const [expanded, setExpanded] = useState(true)
  const [showDetails, setShowDetails] = useState(false)

  const color = serviceColorMap.get(span.serviceName) ?? '#6b7280'
  const startPct = (span.startTime / totalDuration) * 100
  const widthPct = Math.max((span.duration / totalDuration) * 100, 0.5)
  const hasChildren = (span.children?.length ?? 0) > 0

  return (
    <>
      <div
        className="flex items-center gap-2 py-1 px-2 hover:bg-gray-800/50 group rounded cursor-pointer"
        onClick={() => setShowDetails(!showDetails)}
      >
        {/* Indent + expand */}
        <div className="flex items-center shrink-0" style={{ paddingLeft: depth * 16 }}>
          {hasChildren ? (
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
              className="p-0.5 hover:text-gray-200 text-gray-500"
            >
              {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
          ) : (
            <span className="w-5" />
          )}
        </div>

        {/* Service + operation */}
        <div className="w-56 shrink-0 min-w-0 flex items-center gap-1.5">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ background: color }}
          />
          <div className="min-w-0">
            <span className="text-xs text-gray-200 truncate block">{span.operationName}</span>
            <span className="text-[10px] text-gray-500 truncate block">{span.serviceName}</span>
          </div>
          {span.status === 'error' && (
            <AlertCircle size={12} className="text-red-400 shrink-0" />
          )}
        </div>

        {/* Waterfall bar */}
        <div className="flex-1 relative h-5 bg-gray-800 rounded-sm overflow-hidden">
          <div
            className="absolute top-0 h-full rounded-sm transition-all"
            style={{
              left: `${startPct}%`,
              width: `${widthPct}%`,
              background: span.status === 'error' ? '#ef4444' : color,
              opacity: 0.8,
            }}
          />
        </div>

        {/* Duration */}
        <span className="text-xs font-mono text-gray-400 shrink-0 w-16 text-right">
          {span.duration < 1 ? `${(span.duration * 1000).toFixed(0)}μs`
            : span.duration < 1000 ? `${span.duration.toFixed(1)}ms`
            : `${(span.duration / 1000).toFixed(2)}s`}
        </span>
      </div>

      {/* Details panel */}
      {showDetails && (
        <div className="mx-3 mb-1 px-3 py-2 rounded bg-gray-950 border border-gray-800 text-xs">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-gray-600 mb-1">Span ID</p>
              <p className="font-mono text-gray-400 break-all">{span.spanId}</p>
            </div>
            <div>
              <p className="text-gray-600 mb-1">Status</p>
              <p className={cn('font-semibold', span.status === 'error' ? 'text-red-400' : 'text-green-400')}>
                {span.status.toUpperCase()}
              </p>
            </div>
          </div>
          {span.tags && Object.keys(span.tags).length > 0 && (
            <div className="mt-2">
              <p className="text-gray-600 mb-1">Tags</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(span.tags).map(([k, v]) => (
                  <span key={k} className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
                    <span className="text-gray-600">{k}=</span>{v}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Children */}
      {expanded && span.children?.map((child) => (
        <SpanRow
          key={child.spanId}
          span={child}
          totalDuration={totalDuration}
          serviceColorMap={serviceColorMap}
          depth={depth + 1}
        />
      ))}
    </>
  )
}

export function TraceWaterfall({ spans, traceId, title }: TraceWaterfallProps) {
  if (!spans || spans.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 bg-gray-900 rounded-lg border border-gray-800 text-gray-600 text-xs">
        No trace data
      </div>
    )
  }

  // Assign colors to services
  const services = Array.from(new Set(spans.map((s) => s.serviceName)))
  const serviceColorMap = new Map(
    services.map((svc, i) => [svc, SERVICE_COLORS[i % SERVICE_COLORS.length]])
  )

  // Total duration = max(start + duration)
  const totalDuration = Math.max(...spans.map((s) => s.startTime + s.duration), 1)

  // Build tree
  const roots = buildTree(spans)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800 bg-gray-950">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wide">
            {title ?? 'Trace Waterfall'}
          </span>
          {traceId && (
            <span className="text-xs font-mono text-gray-600">{traceId.slice(0, 16)}...</span>
          )}
          <span className="text-xs text-gray-600">({spans.length} spans)</span>
        </div>
        <span className="text-xs text-gray-500 font-mono">
          Total: {totalDuration < 1000 ? `${totalDuration.toFixed(1)}ms` : `${(totalDuration / 1000).toFixed(2)}s`}
        </span>
      </div>

      {/* Column headers */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-gray-800 bg-gray-950/50 text-xs text-gray-600">
        <div className="w-5 shrink-0" />
        <div className="w-56 shrink-0">Operation / Service</div>
        <div className="flex-1">Timeline</div>
        <div className="w-16 text-right shrink-0">Duration</div>
      </div>

      {/* Service legend */}
      <div className="flex flex-wrap gap-2 px-3 py-1.5 border-b border-gray-800 bg-gray-950/30">
        {services.map((svc) => (
          <span key={svc} className="flex items-center gap-1.5 text-xs text-gray-400">
            <span className="w-2 h-2 rounded-full" style={{ background: serviceColorMap.get(svc) }} />
            {svc}
          </span>
        ))}
      </div>

      {/* Spans */}
      <div className="overflow-y-auto max-h-96">
        {roots.map((span) => (
          <SpanRow
            key={span.spanId}
            span={span}
            totalDuration={totalDuration}
            serviceColorMap={serviceColorMap}
            depth={0}
          />
        ))}
      </div>
    </div>
  )
}
