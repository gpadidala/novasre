import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ReferenceArea,
  ResponsiveContainer,
} from 'recharts'
import { format } from 'date-fns'
import { TrendingUp } from 'lucide-react'

export interface MetricDataPoint {
  timestamp: number // Unix timestamp ms
  error_rate?: number
  request_rate?: number
  duration_p99?: number
  yhat_upper?: number
  yhat_lower?: number
  baseline?: number
}

export interface IncidentMarker {
  timestamp: number
  label?: string
  color?: string
}

interface MetricsChartProps {
  data: MetricDataPoint[]
  incidentMarkers?: IncidentMarker[]
  showAnomaly?: boolean
  title?: string
  height?: number
}

function formatValue(value: number, key: string): string {
  if (key === 'error_rate') return `${(value * 100).toFixed(2)}%`
  if (key === 'duration_p99') return `${value.toFixed(0)}ms`
  if (key === 'request_rate') return `${value.toFixed(1)} req/s`
  return value.toFixed(2)
}

const CustomTooltip = ({ active, payload, label }: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: number
}) => {
  if (!active || !payload?.length) return null

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-xl text-xs">
      <p className="text-gray-400 mb-2">
        {label ? format(new Date(label), 'HH:mm:ss') : ''}
      </p>
      {payload.map((item) => (
        <div key={item.name} className="flex items-center gap-2 mb-1">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: item.color }} />
          <span className="text-gray-300 capitalize">{item.name.replace(/_/g, ' ')}:</span>
          <span className="font-mono text-gray-100">{formatValue(item.value, item.name)}</span>
        </div>
      ))}
    </div>
  )
}

export function MetricsChart({
  data,
  incidentMarkers = [],
  showAnomaly = false,
  title,
  height = 240,
}: MetricsChartProps) {
  if (!data || data.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center bg-gray-900 rounded-lg border border-gray-800 text-gray-600 gap-2"
        style={{ height }}
      >
        <TrendingUp size={24} />
        <p className="text-xs">No metrics data</p>
      </div>
    )
  }

  const hasErrorRate = data.some((d) => d.error_rate != null)
  const hasRequestRate = data.some((d) => d.request_rate != null)
  const hasDuration = data.some((d) => d.duration_p99 != null)

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
      {title && (
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">{title}</p>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
          <XAxis
            dataKey="timestamp"
            type="number"
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => format(new Date(v), 'HH:mm')}
            tick={{ fontSize: 10, fill: '#6b7280' }}
            axisLine={{ stroke: '#374151' }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#6b7280' }}
            axisLine={false}
            tickLine={false}
            width={40}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }}
            formatter={(value: string) => (
              <span style={{ color: '#9ca3af' }}>{value.replace(/_/g, ' ')}</span>
            )}
          />

          {/* Anomaly band */}
          {showAnomaly && data.some((d) => d.yhat_upper != null) && (
            <ReferenceArea
              fill="#7c3aed"
              fillOpacity={0.05}
              stroke="none"
            />
          )}

          {/* Incident markers */}
          {incidentMarkers.map((marker, i) => (
            <ReferenceLine
              key={i}
              x={marker.timestamp}
              stroke={marker.color ?? '#ef4444'}
              strokeDasharray="4 2"
              label={{
                value: marker.label ?? 'Incident',
                fontSize: 10,
                fill: marker.color ?? '#ef4444',
              }}
            />
          ))}

          {/* Anomaly bound lines */}
          {showAnomaly && data.some((d) => d.yhat_upper != null) && (
            <Line
              type="monotone"
              dataKey="yhat_upper"
              stroke="#7c3aed"
              strokeWidth={1}
              strokeDasharray="3 2"
              dot={false}
              name="anomaly_upper"
              opacity={0.5}
            />
          )}
          {showAnomaly && data.some((d) => d.yhat_lower != null) && (
            <Line
              type="monotone"
              dataKey="yhat_lower"
              stroke="#7c3aed"
              strokeWidth={1}
              strokeDasharray="3 2"
              dot={false}
              name="anomaly_lower"
              opacity={0.5}
            />
          )}

          {/* Baseline overlay */}
          {data.some((d) => d.baseline != null) && (
            <Line
              type="monotone"
              dataKey="baseline"
              stroke="#6b7280"
              strokeWidth={1}
              strokeDasharray="5 3"
              dot={false}
              name="baseline (yesterday)"
              opacity={0.6}
            />
          )}

          {/* Main metrics */}
          {hasErrorRate && (
            <Line
              type="monotone"
              dataKey="error_rate"
              stroke="#ef4444"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#ef4444' }}
              name="error_rate"
            />
          )}
          {hasRequestRate && (
            <Line
              type="monotone"
              dataKey="request_rate"
              stroke="#22d3ee"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#22d3ee' }}
              name="request_rate"
            />
          )}
          {hasDuration && (
            <Line
              type="monotone"
              dataKey="duration_p99"
              stroke="#c084fc"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#c084fc' }}
              name="duration_p99"
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
