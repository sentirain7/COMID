import { ProgressBar, StatusBadge } from '../shared'
import { useInversePipelineProgress } from '../../hooks/useApiInversePipeline'

/**
 * Wizard ③ — pipeline progress (plan §8, 3s polling).
 *
 * The placeholder→real layered indirection is resolved by the backend and
 * returned as effective_status. Also shows replica group/ensemble readiness.
 */
function PipelineMonitor({ pipelineId, onShowResults }) {
  const { data, isLoading, error } = useInversePipelineProgress(pipelineId)

  if (isLoading) return <p className="text-slate-400 text-sm">Loading progress…</p>
  if (error) return <p className="text-red-400 text-sm">{String(error.message || error)}</p>
  if (!data) return null

  const { total, completed, status_counts: statusCounts, members } = data
  const progressPct = total > 0 ? (completed / total) * 100 : 0
  const allDone = total > 0 && completed === total

  return (
    <div className="space-y-4">
      <section>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-slate-200 font-semibold">Pipeline progress</h3>
          <span className="text-slate-400 text-xs font-mono">{pipelineId}</span>
        </div>
        <ProgressBar progress={progressPct} currentStep={completed} totalSteps={total} />
        <div className="flex flex-wrap gap-2 mt-2 text-xs">
          {Object.entries(statusCounts || {}).map(([status, count]) => (
            <span key={status} className="bg-slate-700/50 rounded px-2 py-1 text-slate-200">
              {status}: {count}
            </span>
          ))}
        </div>
      </section>

      <section>
        <table className="w-full text-xs">
          <thead className="text-slate-400">
            <tr>
              <th className="py-1 px-2 text-left">Plan ID</th>
              <th className="py-1 px-2 text-left">Kind</th>
              <th className="py-1 px-2 text-left">Experiment</th>
              <th className="py-1 px-2">Cand.</th>
              <th className="py-1 px-2">Status</th>
              <th className="py-1 px-2">Replicas</th>
            </tr>
          </thead>
          <tbody className="text-slate-300">
            {(members || []).map((m) => (
              <tr key={m.exp_id} className="border-t border-slate-700/50">
                <td className="py-1 px-2">{m.plan_exp_id || '—'}</td>
                <td className="py-1 px-2">{m.kind || '—'}</td>
                <td className="py-1 px-2 font-mono text-[11px]">{m.effective_exp_id}</td>
                <td className="py-1 px-2 text-center">{m.candidate_index ?? '—'}</td>
                <td className="py-1 px-2 text-center">
                  <StatusBadge status={m.effective_status} size="sm" />
                </td>
                <td className="py-1 px-2 text-center">
                  {m.replicate_group_id ? (
                    <span
                      className={
                        m.ensemble_ready ? 'text-emerald-300' : 'text-slate-400'
                      }
                    >
                      {m.ensemble_ready ? 'ensemble ✓' : 'group'}
                    </span>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <button
        type="button"
        onClick={onShowResults}
        className={`px-4 py-2 rounded text-sm font-semibold text-white ${
          allDone ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-slate-700 hover:bg-slate-600'
        }`}
      >
        {allDone ? 'View results →' : 'View partial results →'}
      </button>
    </div>
  )
}

export default PipelineMonitor
