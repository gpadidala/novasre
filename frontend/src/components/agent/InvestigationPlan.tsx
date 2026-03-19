import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { InvestigationPlanStep } from '@/lib/api'

interface InvestigationPlanProps {
  steps: InvestigationPlanStep[]
  className?: string
}

function StepIcon({ status }: { status: InvestigationPlanStep['status'] }) {
  switch (status) {
    case 'done':
      return <CheckCircle2 size={16} className="text-green-400 shrink-0" />
    case 'running':
      return <Loader2 size={16} className="text-yellow-400 animate-spin shrink-0" />
    case 'failed':
      return <XCircle size={16} className="text-red-400 shrink-0" />
    default:
      return <Circle size={16} className="text-gray-600 shrink-0" />
  }
}

export function InvestigationPlan({ steps, className }: InvestigationPlanProps) {
  const doneCount = steps.filter((s) => s.status === 'done').length
  const progress = steps.length > 0 ? (doneCount / steps.length) * 100 : 0

  const agentColors: Record<string, string> = {
    metrics: 'text-purple-400',
    logs: 'text-yellow-400',
    traces: 'text-cyan-400',
    profiles: 'text-orange-400',
    frontend: 'text-pink-400',
    k8s: 'text-blue-400',
    planner: 'text-indigo-400',
    synthesizer: 'text-green-400',
  }

  return (
    <div className={cn('space-y-3', className)}>
      {/* Progress bar */}
      {steps.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-gray-500">Progress</span>
            <span className="text-xs text-gray-400">{doneCount}/{steps.length}</span>
          </div>
          <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Steps */}
      {steps.length === 0 ? (
        <div className="text-xs text-gray-600 italic py-2">
          Investigation plan will appear here...
        </div>
      ) : (
        <ol className="space-y-2">
          {steps.map((step, idx) => (
            <li
              key={step.id}
              className={cn(
                'flex items-start gap-2 p-2 rounded-lg transition-colors',
                step.status === 'running' ? 'bg-yellow-500/5 border border-yellow-500/20' : '',
                step.status === 'done' ? 'opacity-70' : ''
              )}
            >
              <div className="mt-0.5">
                <StepIcon status={step.status} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-gray-600">{idx + 1}.</span>
                  {step.agent && (
                    <span className={cn('text-xs font-semibold capitalize', agentColors[step.agent] ?? 'text-gray-400')}>
                      [{step.agent}]
                    </span>
                  )}
                </div>
                <p className={cn(
                  'text-xs mt-0.5',
                  step.status === 'done' ? 'text-gray-500' : 'text-gray-300'
                )}>
                  {step.description}
                </p>
                {step.question && step.status !== 'done' && (
                  <p className="text-xs text-gray-500 italic mt-0.5 line-clamp-2">
                    "{step.question}"
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
