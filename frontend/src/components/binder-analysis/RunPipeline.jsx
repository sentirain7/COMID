import { StatusBadge, ProgressBar } from '../shared'
import { INTENT_KIND_LABELS } from '../../lib/constants'

const SIMULATE_STEPS = ['planned', 'queued', 'running', 'completed']
const DB_MATCH_STEPS = ['planned', 'matched']

function getSteps(route) {
  return route === 'db_match' ? DB_MATCH_STEPS : SIMULATE_STEPS
}

function getStepIndex(steps, status) {
  if (status === 'failed' || status === 'blocked') {
    // failed/blocked: show at the step they were on (last non-terminal)
    return steps.length - 1
  }
  const idx = steps.indexOf(status)
  return idx >= 0 ? idx : 0
}

function StepIndicator({ steps, status }) {
  const isFailed = status === 'failed'
  const isBlocked = status === 'blocked'
  const currentIdx = getStepIndex(steps, status)
  const activeIdx = steps.indexOf(status)

  return (
    <div className="flex items-center gap-0">
      {steps.map((step, i) => {
        const isActive = i === activeIdx
        const isCompleted = activeIdx >= 0 ? i < activeIdx : i < currentIdx
        const isLast = i === steps.length - 1

        let dotColor = 'bg-slate-600 border-slate-500' // future
        if (isFailed && i === currentIdx) {
          dotColor = 'bg-red-500 border-red-400'
        } else if (isBlocked && i === currentIdx) {
          dotColor = 'bg-amber-500 border-amber-400'
        } else if (isActive && !isFailed && !isBlocked) {
          dotColor = 'bg-blue-500 border-blue-400 ring-2 ring-blue-500/30'
        } else if (isCompleted) {
          dotColor = 'bg-emerald-500 border-emerald-400'
        }

        let lineColor = 'bg-slate-700'
        if (isCompleted) lineColor = 'bg-emerald-500/60'

        return (
          <div key={step} className="flex items-center">
            <div
              className={`w-2 h-2 rounded-full border ${dotColor}`}
              title={step}
            />
            {!isLast && (
              <div className={`w-4 h-0.5 ${lineColor}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function RunCard({ run }) {
  const steps = getSteps(run.route)
  const shortKey = run.run_key?.length > 16
    ? run.run_key.slice(0, 16) + '…'
    : run.run_key

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 flex items-center gap-3">
      <StepIndicator steps={steps} status={run.status} />

      <div className="flex items-center gap-2 flex-1 min-w-0">
        <StatusBadge status={run.status} size="sm" />
        <span className="inline-block rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-1.5 py-0.5 text-[11px]">
          {INTENT_KIND_LABELS[run.intent_kind] || run.intent_kind}
        </span>
      </div>

      <div className="flex items-center gap-2 text-[11px] text-slate-400 shrink-0">
        {run.temperature_K != null && <span>{run.temperature_K}K</span>}
        {run.crystal_material && (
          <>
            <span className="text-slate-600">·</span>
            <span>{run.crystal_material}</span>
          </>
        )}
        {run.route && (
          <>
            <span className="text-slate-600">·</span>
            <span>{run.route}</span>
          </>
        )}
      </div>

      <div className="font-mono text-[10px] text-slate-500 truncate max-w-[120px]" title={run.run_key}>
        {shortKey}
      </div>
    </div>
  )
}

function RunPipeline({ runs = [] }) {
  if (runs.length === 0) {
    return <p className="text-sm text-slate-400">No runs yet.</p>
  }

  const completedCount = runs.filter((r) => r.status === 'completed' || r.status === 'matched').length
  const failedCount = runs.filter((r) => r.status === 'failed').length
  const total = runs.length
  const progress = total > 0 ? (completedCount / total) * 100 : 0

  return (
    <div className="space-y-3">
      {/* Overall progress */}
      <div className="flex items-center gap-3">
        <ProgressBar
          progress={progress}
          currentStep={completedCount}
          totalSteps={total}
          size="sm"
          color={failedCount > 0 ? 'yellow' : 'blue'}
        />
        {failedCount > 0 && (
          <span className="text-[11px] text-red-400 font-medium">
            {failedCount} failed
          </span>
        )}
      </div>

      {/* Run cards */}
      <div className="space-y-1.5">
        {runs.map((run) => (
          <RunCard key={run.run_key} run={run} />
        ))}
      </div>
    </div>
  )
}

export default RunPipeline
