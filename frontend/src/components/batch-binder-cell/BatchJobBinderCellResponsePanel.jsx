import clsx from 'clsx'
import { Link } from 'react-router-dom'
import { ROUTE_KEYS, ROUTE_META } from '../../navigation/routeMeta'
import { PriorityBadge } from '../shared'

function BatchJobBinderCellResponsePanel({
  latestResponse,
  isSubmission,
  excludedExpIds = new Set(),
  onToggleExclude,
  onExcludeAllSimilar,
  onClearExclusions,
}) {
  if (!latestResponse) {
    return null
  }

  const hasSimilarJobs = latestResponse.similar_job_count > 0
  const hasSimilarNonDup = (latestResponse.jobs || []).some(
    (j) => j.similar_existing && j.status !== 'duplicate'
  )

  return (
    <div className="card p-4 space-y-3">
      <h2 className="text-sm font-semibold text-slate-300">
        {isSubmission ? 'Batch Job Binder Cell Submission Result' : 'Batch Job Binder Cell Scenario Preview'}
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-8 gap-2 text-xs">
        <div className="bg-slate-700/40 rounded p-2 text-slate-300">id: <span className="text-white">{latestResponse.batch_job_id}</span></div>
        <div className="bg-slate-700/40 rounded p-2 text-slate-300">new: <span className="text-white">{latestResponse.new}</span></div>
        <div className="bg-slate-700/40 rounded p-2 text-slate-300">duplicates: <span className="text-white">{latestResponse.duplicates}</span></div>
        <div className="bg-slate-700/40 rounded p-2 text-slate-300">submitted: <span className="text-white">{latestResponse.submitted}</span></div>
        <div className="bg-slate-700/40 rounded p-2 text-slate-300">errors: <span className="text-white">{latestResponse.errors}</span></div>
        <div className={clsx(
          'rounded p-2 text-slate-300',
          latestResponse.blocked > 0 ? 'bg-amber-500/20 border border-amber-500/40' : 'bg-slate-700/40'
        )}>blocked: <span className="text-white">{latestResponse.blocked || 0}</span></div>
        <div className={clsx(
          'rounded p-2 text-slate-300',
          hasSimilarJobs ? 'bg-cyan-500/20 border border-cyan-500/40' : 'bg-slate-700/40'
        )}>similar: <span className="text-white">{latestResponse.similar_job_count || 0}</span></div>
        <div className={clsx(
          'rounded p-2 text-slate-300',
          excludedExpIds.size > 0 ? 'bg-orange-500/20 border border-orange-500/40' : 'bg-slate-700/40'
        )}>excluded: <span className="text-white">{excludedExpIds.size}</span></div>
      </div>

      {/* FF blocked items warning */}
      {latestResponse.ff_blocked_items?.length > 0 && (
        <div className="text-[10px] text-amber-400/90 mt-2 px-1 space-y-0.5">
          <div>
            {latestResponse.ff_blocked_items.length} species require FF artifacts before submission.
          </div>
          <Link
            to={`${ROUTE_META[ROUTE_KEYS.MOLECULES].path}?mol_id=${encodeURIComponent(latestResponse.ff_blocked_items[0]?.item_id || '')}`}
            className="inline-block text-blue-400 hover:text-blue-300 underline"
          >
            Manage FF artifacts in Molecules catalog →
          </Link>
        </div>
      )}

      {!isSubmission && (hasSimilarNonDup || excludedExpIds.size > 0) && (
        <div className="flex items-center gap-2">
          {hasSimilarNonDup && (
            <button
              className="px-2 py-1 rounded text-xs bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/30 transition-colors"
              onClick={onExcludeAllSimilar}
            >
              Exclude All Similar
            </button>
          )}
          {excludedExpIds.size > 0 && (
            <button
              className="px-2 py-1 rounded text-xs bg-slate-700/40 border border-slate-600 text-slate-300 hover:bg-slate-700 transition-colors"
              onClick={onClearExclusions}
            >
              Clear Exclusions
            </button>
          )}
        </div>
      )}

      {hasSimilarJobs && !isSubmission && excludedExpIds.size === 0 && (
        <div className="bg-cyan-900/30 border border-cyan-500/40 rounded p-3 text-sm text-cyan-200">
          <strong>{latestResponse.similar_job_count}</strong> job(s) have similar completed experiments in the database.
          You will be asked to choose a priority handling option before submitting.
        </div>
      )}

      <div className="max-h-[320px] overflow-y-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-400 text-center border-b border-slate-700">
              {!isSubmission && <th className="py-2 w-8"></th>}
              <th className="py-2">exp_id</th>
              <th className="py-2">binder</th>
              <th className="py-2">temp</th>
              <th className="py-2">tier</th>
              <th className="py-2">priority</th>
              <th className="py-2">status</th>
              <th className="py-2">similar</th>
            </tr>
          </thead>
          <tbody>
            {(latestResponse.jobs || []).map((job) => {
              const isDup = job.status === 'duplicate'
              const isExcluded = excludedExpIds.has(job.exp_id)

              return (
                <tr key={job.exp_id} className={clsx(
                  'border-b border-slate-800 text-slate-300 text-center',
                  job.similar_existing && !isExcluded && 'bg-cyan-900/20',
                  isExcluded && 'opacity-40',
                )}>
                  {!isSubmission && (
                    <td className="py-2">
                      {!isDup ? (
                        <input
                          type="checkbox"
                          checked={!isExcluded}
                          onChange={() => onToggleExclude(job.exp_id)}
                          className="w-3.5 h-3.5 rounded border-slate-500 bg-slate-700 text-blue-500 focus:ring-blue-500/30 cursor-pointer"
                          title={isExcluded ? 'Include in submission' : 'Exclude from submission'}
                        />
                      ) : (
                        <span className="text-slate-600 text-[10px]">-</span>
                      )}
                    </td>
                  )}
                  <td className={clsx('py-2 font-mono text-[11px]', isExcluded && 'line-through')}>{job.exp_id}</td>
                  <td className="py-2">{job.binder_type}</td>
                  <td className="py-2">{job.temperature_k}</td>
                  <td className="py-2">{job.tier}</td>
                  <td className="py-2">
                    <div className="flex justify-center">
                      <PriorityBadge priority={job.priority || 'medium'} />
                    </div>
                  </td>
                  <td className="py-2">{isExcluded ? 'excluded' : job.status}</td>
                  <td className="py-2">
                    {job.similar_existing ? (
                      <span className="text-cyan-400" title={job.similar_experiment_ids?.join(', ')}>
                        {job.similar_experiment_ids?.length || 0}
                      </span>
                    ) : (
                      <span className="text-slate-500">-</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default BatchJobBinderCellResponsePanel
