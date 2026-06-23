import { useMemo } from 'react'
import clsx from 'clsx'
import { useExperiments } from '../../hooks/useApi'
import { StatusBadge } from '../shared/index'
import { RefreshCw, FlaskConical } from 'lucide-react'
import { getVisibleEIntraMethodDisplay } from '../../lib/eIntraMethod'
import { useSubmissionEIntraMethod } from '../../hooks/useSubmissionEIntraMethod'

function DynamicsExperimentList({ selectedMolId, selectedExpId, onSelectExp }) {
  // PR 3 (v01.04.18): Use Settings-based E_intra method for experiment filtering
  // instead of hardcoded 'single_molecule_vacuum' to maintain SSOT consistency
  const { effectiveEIntraMethod } = useSubmissionEIntraMethod()

  const filters = useMemo(
    () => ({
      study_type: 'single_molecule_vacuum',
      e_intra_method: effectiveEIntraMethod,
      status: 'completed',
      additive_mol_id: selectedMolId,
      limit: 50,
    }),
    [selectedMolId, effectiveEIntraMethod],
  )

  const { data, loading } = useExperiments(filters, 10000, { enabled: Boolean(selectedMolId) })
  const experiments = data?.experiments || []
  const totalCount = data?.filtered_total_count ?? experiments.length

  if (!selectedMolId) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500">
        <div className="text-center">
          <FlaskConical className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p className="text-xs">Select a molecule</p>
        </div>
      </div>
    )
  }

  if (loading && experiments.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <RefreshCw className="w-5 h-5 text-blue-400 animate-spin" />
      </div>
    )
  }

  if (experiments.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500">
        <div className="text-center px-3">
          <FlaskConical className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p className="text-xs">No dynamics simulations</p>
          <p className="text-[10px] text-slate-600 mt-1">Submit a single-molecule job to generate data</p>
        </div>
      </div>
    )
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="text-[10px] text-slate-500 px-2 py-1.5 sticky top-0 bg-slate-800 z-10 border-b border-slate-700">
        {totalCount > experiments.length
          ? `Showing ${experiments.length} of ${totalCount}`
          : `${experiments.length} experiment${experiments.length > 1 ? 's' : ''}`
        } for {selectedMolId}
      </div>
      {experiments.map((exp) => (
        (() => {
          const methodDisplay = getVisibleEIntraMethodDisplay(exp.e_intra_method)
          return (
            <button
              key={exp.exp_id}
              onClick={() => onSelectExp(exp.exp_id)}
              className={clsx(
                'w-full text-left px-2 py-2 border-b border-slate-700/50 transition-colors',
                selectedExpId === exp.exp_id
                  ? 'bg-blue-500/15 border-l-2 border-l-blue-500'
                  : 'hover:bg-slate-700/40 border-l-2 border-l-transparent',
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-xs text-slate-200 font-mono truncate">
                  {exp.temperature_k != null ? `${exp.temperature_k} K` : exp.exp_id}
                </span>
                <StatusBadge status={exp.status} size="sm" />
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px]">
                <span className="truncate text-cyan-300">
                  {methodDisplay.shortLabel || methodDisplay.label}
                </span>
                {exp.wall_time_seconds != null && (
                  <span className="text-slate-500">
                    {(exp.wall_time_seconds / 60).toFixed(1)} min
                  </span>
                )}
              </div>
            </button>
          )
        })()
      ))}
    </div>
  )
}

export default DynamicsExperimentList
