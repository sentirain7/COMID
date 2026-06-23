import { getAdditiveDisplayName } from '../../lib/additiveLabel'

function BatchJobBinderCellScenarioPreviewPanel({
  scenarioPreview,
  pending,
  error,
  additiveCatalog,
  binderCodeMap,
  agingCodeMap,
  excludedExpIds,
}) {
  return (
    <div className="text-sm text-slate-300 md:col-span-4">
      <div className="text-sm font-semibold mb-1">Scenario Preview</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 min-h-[80px]">
        {pending ? (
          <div className="flex items-center justify-center h-16">
            <div className="w-5 h-5 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          </div>
        ) : scenarioPreview?.jobs?.length > 0 ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
              <span>{scenarioPreview.jobs.length} jobs</span>
              {scenarioPreview.new > 0 && <span className="text-green-400">({scenarioPreview.new} new)</span>}
              {scenarioPreview.duplicates > 0 && <span className="text-slate-500">({scenarioPreview.duplicates} dup)</span>}
              {scenarioPreview.errors > 0 && <span className="text-red-400">({scenarioPreview.errors} err)</span>}
              {excludedExpIds?.size > 0 && <span className="text-orange-400">({excludedExpIds.size} excluded)</span>}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {scenarioPreview.jobs.map((job) => {
                const binderCode = binderCodeMap[job.binder_type] || job.binder_type
                const agingCode = job.aging_state
                  ? (agingCodeMap[job.aging_state] || job.aging_state.substring(0, 2).toUpperCase())
                  : ''
                const temp = job.temperature_k || ''
                const additive = job.additive_type && job.additive_type !== '__none__'
                  ? `+${getAdditiveDisplayName(job.additive_type, additiveCatalog)}`
                  : ''
                const label = `${binderCode}${agingCode ? '-' + agingCode : ''}-${temp}K${additive}`

                const isExcluded = excludedExpIds?.has(job.exp_id)
                const isNew = job.status === 'new' || job.status === 'pending'
                const isDup = job.status === 'duplicate' || job.status === 'skipped'
                const isErr = job.status === 'error' || job.status === 'failed'

                return (
                  <span
                    key={job.exp_id}
                    className={[
                      'px-1.5 py-0.5 rounded text-[10px] border whitespace-nowrap',
                      isExcluded
                        ? 'opacity-40 line-through bg-orange-500/10 border-orange-500/30 text-orange-300'
                        : isNew
                        ? 'bg-green-500/20 border-green-500/60 text-green-300'
                        : isDup
                        ? 'bg-slate-700/40 border-slate-600 text-slate-400'
                        : isErr
                        ? 'bg-red-500/20 border-red-500/60 text-red-300'
                        : 'bg-slate-700/40 border-slate-600 text-slate-300',
                    ].join(' ')}
                    title={job.exp_id}
                  >
                    {label}
                  </span>
                )
              })}
            </div>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-16 text-xs text-red-400">
            Error: {error}
          </div>
        ) : (
          <div className="flex items-center justify-center h-16 text-xs text-slate-500">
            Click &quot;Build Scenario&quot; to preview
          </div>
        )}
      </div>
    </div>
  )
}

export default BatchJobBinderCellScenarioPreviewPanel
