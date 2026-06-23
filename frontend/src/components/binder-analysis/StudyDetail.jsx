import { BINDER_ANALYSIS_STATE_COLORS, BINDER_ANALYSIS_STATE_LABELS, INTENT_KIND_LABELS } from '../../lib/constants'
import { useBinderStudyDetail, useBinderStudyResults } from '../../hooks/useApi'
import RunPipeline from './RunPipeline'
import ResultsPanel from './ResultsPanel'

function formatDate(value) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

const MOCK_METRICS = ['density', 'cohesive_energy_density', 'viscosity']
const MOCK_TEMPS = [273, 293, 313, 333, 373]

function ResultsPlaceholder({ state, totalRuns }) {
  const stateMsg = {
    intake: 'Study is being analyzed...',
    clarifying: 'Waiting for your input...',
    planning: 'Building simulation plan...',
    awaiting_confirmation: 'Awaiting plan confirmation...',
    failed: 'Study failed — no results available.',
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4 text-center">
        <p className="text-xs text-slate-400">
          {stateMsg[state] || 'Results will appear here when runs complete.'}
        </p>
        {totalRuns > 0 && (
          <p className="mt-1 text-[11px] text-slate-500">{totalRuns} runs planned</p>
        )}
      </div>

      {/* Mock table */}
      <div className="overflow-x-auto opacity-40 pointer-events-none select-none">
        <table className="w-full text-xs text-center">
          <thead className="bg-slate-800 border-b border-slate-700/50">
            <tr className="text-slate-500">
              <th className="px-3 py-2 font-medium">Run</th>
              <th className="px-3 py-2 font-medium">Temp (K)</th>
              {MOCK_METRICS.map((m) => (
                <th key={m} className="px-3 py-2 font-medium">{m}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/30">
            {MOCK_TEMPS.map((t) => (
              <tr key={t}>
                <td className="px-3 py-2 text-slate-600">run-••••</td>
                <td className="px-3 py-2 text-slate-600">{t}</td>
                {MOCK_METRICS.map((m) => (
                  <td key={m} className="px-3 py-2 text-slate-600">—</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mock chart area */}
      <div className="rounded-lg border border-dashed border-slate-700/50 bg-slate-800/20 h-48 flex items-center justify-center opacity-40">
        <div className="text-center">
          <div className="text-slate-600 text-xs">Chart Preview</div>
          <div className="mt-2 flex items-end justify-center gap-1">
            {[32, 48, 40, 56, 44, 60, 52].map((h, i) => (
              <div key={i} className="w-4 rounded-t bg-slate-700/60" style={{ height: h }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function StudyDetail({ studyId }) {
  const { data: detail, loading: detailLoading } = useBinderStudyDetail(studyId, 5000)
  const { data: resultsData, loading: resultsLoading } = useBinderStudyResults(studyId, 10000)

  if (detailLoading && !detail) {
    return <p className="text-sm text-slate-400">Loading study...</p>
  }

  if (!detail) {
    return <p className="text-sm text-slate-400">Study not found.</p>
  }

  const stateColor = BINDER_ANALYSIS_STATE_COLORS[detail.state] || 'bg-slate-600 text-slate-200'
  const stateLabel = BINDER_ANALYSIS_STATE_LABELS[detail.state] || detail.state

  const planSummary = detail.plan_summary || {}
  const normalizedIntent = detail.normalized_intent || {}
  const showResults = ['completed', 'executing'].includes(detail.state)

  return (
    <div className="space-y-3">
      <div className="card p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">Binder Study</div>
            <h2 className="mt-1 text-lg font-semibold text-white leading-snug">
              {detail.problem_text || detail.study_id}
            </h2>
            <div className="mt-1 font-mono text-xs text-slate-400">{detail.study_id}</div>
            <div className="mt-2 text-xs text-slate-500">Created {formatDate(detail.created_at)}</div>
          </div>
          <span className={`inline-flex items-center rounded px-2.5 py-1 text-xs font-medium ${stateColor}`}>
            {stateLabel}
          </span>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-4">
          {normalizedIntent.intent_kind && (
            <div className="rounded-lg bg-slate-800/60 p-3">
              <div className="text-[11px] text-slate-500">Intent</div>
              <div className="mt-1 text-sm font-medium text-white">
                {INTENT_KIND_LABELS[normalizedIntent.intent_kind] || normalizedIntent.intent_kind}
              </div>
            </div>
          )}
          <div className="rounded-lg bg-slate-800/60 p-3">
            <div className="text-[11px] text-slate-500">Total Runs</div>
            <div className="mt-1 text-xl font-semibold text-white">{detail.total_runs || 0}</div>
          </div>
          {detail.run_summary && Object.entries(detail.run_summary).map(([status, count]) => (
            <div key={status} className="rounded-lg bg-slate-800/60 p-3">
              <div className="text-[11px] text-slate-500">{status}</div>
              <div className="mt-1 text-xl font-semibold text-white">{count}</div>
            </div>
          ))}
        </div>

        {planSummary.total_runs != null && (
          <div className="mt-4 rounded-lg border border-slate-700 bg-slate-800/40 p-3">
            <div className="text-[11px] text-slate-500 mb-1">Plan Summary</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-slate-300">
              <div>Total runs: <span className="text-white font-medium">{planSummary.total_runs}</span></div>
              {planSummary.planned_count != null && (
                <div>Simulations: <span className="text-white font-medium">{planSummary.planned_count}</span></div>
              )}
              {planSummary.matched_count != null && (
                <div>DB matches: <span className="text-white font-medium">{planSummary.matched_count}</span></div>
              )}
              {planSummary.prerequisite_count != null && planSummary.prerequisite_count > 0 && (
                <div>Prerequisites: <span className="text-white font-medium">{planSummary.prerequisite_count}</span></div>
              )}
              {planSummary.estimated_gpu_hours != null && (
                <div>Est. GPU hours: <span className="text-white font-medium">{planSummary.estimated_gpu_hours}</span></div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="card p-3">
        <h3 className="mb-2 text-xs font-semibold text-slate-400 uppercase tracking-wide">Runs</h3>
        <RunPipeline runs={detail.runs || []} />
      </div>

      <div className="card p-3">
        <h3 className="mb-2 text-xs font-semibold text-slate-400 uppercase tracking-wide">Results</h3>
        {showResults ? (
          <ResultsPanel results={resultsData?.results || []} loading={resultsLoading} />
        ) : (
          <ResultsPlaceholder state={detail.state} totalRuns={detail.total_runs || 0} />
        )}
      </div>
    </div>
  )
}

export default StudyDetail
