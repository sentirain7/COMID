import { useState, useMemo, useEffect } from 'react'
import clsx from 'clsx'
import { FlaskConical, Search } from 'lucide-react'
import { useExperiments } from '../../hooks/useApi'
import DynamicsExperimentList from './DynamicsExperimentList'
import DynamicsExperimentDetail from './DynamicsExperimentDetail'
import { useSubmissionEIntraMethod } from '../../hooks/useSubmissionEIntraMethod'

function DynamicsPanel({ selectedMolId, onSelectMolId, molecules }) {
  const [selectedExpId, setSelectedExpId] = useState(null)
  const [searchTerm, setSearchTerm] = useState('')

  // PR 3 (v01.04.18): Use Settings-based E_intra method for SSOT consistency
  const { effectiveEIntraMethod } = useSubmissionEIntraMethod()

  // Reset selected experiment when molecule changes
  useEffect(() => {
    setSelectedExpId(null)
  }, [selectedMolId])

  // Fetch SM experiments to build molecule-level summary.
  // TODO: replace with a dedicated aggregation endpoint (e.g.
  // GET /experiments/molecule-counts?study_type=<method>)
  // once the experiment count grows beyond this client-side limit.
  const smFilters = useMemo(
    () => ({
      study_type: 'single_molecule_vacuum',
      e_intra_method: effectiveEIntraMethod,
      status: 'completed',
      limit: 2000,
    }),
    [effectiveEIntraMethod],
  )
  const { data: smData } = useExperiments(smFilters, 15000)
  const smExperiments = useMemo(() => smData?.experiments || [], [smData])

  // Group experiments by additive_mol_id to get counts
  const molExpCounts = useMemo(() => {
    const counts = {}
    for (const exp of smExperiments) {
      const mid = exp.additive_mol_id || exp.additive_label
      if (mid) counts[mid] = (counts[mid] || 0) + 1
    }
    return counts
  }, [smExperiments])

  // Molecules that have SM experiments
  const molsWithExperiments = useMemo(() => {
    const ids = Object.keys(molExpCounts)
    if (!searchTerm) return ids.sort()
    const term = searchTerm.toLowerCase()
    return ids.filter((id) => id.toLowerCase().includes(term)).sort()
  }, [molExpCounts, searchTerm])

  if (!molecules || molecules.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-slate-400">
        <div className="text-center">
          <FlaskConical className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Loading molecules...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="grid gap-3 md:grid-cols-[2fr_3fr_5fr] h-full min-h-0">
      {/* Left: Molecule list */}
      <div className="card flex flex-col min-h-0 overflow-hidden">
        <div className="px-2 py-1.5 border-b border-slate-700 flex-shrink-0">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500" />
            <input
              type="text"
              placeholder="Search molecules..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-6 pr-2 py-1 text-xs bg-slate-800 border border-slate-700 rounded text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
            />
          </div>
        </div>
        <div className="overflow-y-auto flex-1">
          {molsWithExperiments.length === 0 ? (
            <div className="p-3 text-center text-xs text-slate-500">
              No molecules with dynamics data
            </div>
          ) : (
            molsWithExperiments.map((molId) => (
              <button
                key={molId}
                onClick={() => onSelectMolId(molId)}
                className={clsx(
                  'w-full text-left px-2 py-1.5 border-b border-slate-700/50 transition-colors',
                  selectedMolId === molId
                    ? 'bg-blue-500/15 border-l-2 border-l-blue-500'
                    : 'hover:bg-slate-700/40 border-l-2 border-l-transparent',
                )}
              >
                <div className="text-xs text-slate-200 truncate">{molId}</div>
                <div className="text-[10px] text-slate-500">
                  {molExpCounts[molId]} run{molExpCounts[molId] > 1 ? 's' : ''}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Middle: Experiment list for selected molecule */}
      <div className="card min-h-0 overflow-hidden">
        <DynamicsExperimentList
          selectedMolId={selectedMolId}
          selectedExpId={selectedExpId}
          onSelectExp={setSelectedExpId}
        />
      </div>

      {/* Right: Experiment detail */}
      <div className="card min-h-0 overflow-hidden">
        <DynamicsExperimentDetail expId={selectedExpId} />
      </div>
    </div>
  )
}

export default DynamicsPanel
