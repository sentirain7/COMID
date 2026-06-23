import { useEffect, useState } from 'react'
import { RefreshCw, AlertTriangle, Box, Maximize2, Minimize2 } from 'lucide-react'
import { getStructureXYZ, getAvailableStages } from '../../api/client'
import clsx from 'clsx'
import { SimpleViewer } from './SimpleViewer'

// Stage display labels
const STAGE_LABELS = {
  initial: 't=0 (Initial)',
  nvt_equilibration: 'NVT Equilibration',
  npt_production: 'NPT Production',
  viscosity_nemd: 'Viscosity NEMD',
  final: 'Final',
}

export function MoleculeViewer({ expId, viewerHeight = 'h-72' }) {
  const [stage, setStage] = useState('initial')
  const [structureInfo, setStructureInfo] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [availableStages, setAvailableStages] = useState([])
  const [tier, setTier] = useState('')
  const [isExpanded, setIsExpanded] = useState(false)

  // Load available stages when expId changes
  useEffect(() => {
    if (!expId) return

    setLoading(true)
    setError(null)

    getAvailableStages(expId)
      .then(data => {
        setAvailableStages(data.stages || [])
        setTier(data.tier || '')
        // Select first available stage if current not available
        if (data.stages?.length > 0) {
          setStage(prev => data.stages.includes(prev) ? prev : data.stages[0])
        }
      })
      .catch(err => {
        console.error('Failed to load stages:', err)
        setError('Failed to load available stages')
      })
      .finally(() => setLoading(false))
  }, [expId])

  // Load structure when stage changes
  useEffect(() => {
    if (!expId || !stage || availableStages.length === 0) return

    setLoading(true)
    setError(null)

    getStructureXYZ(expId, stage)
      .then(data => {
        setStructureInfo(data)
      })
      .catch(err => {
        console.error('Failed to load structure:', err)
        setError(err.response?.data?.detail?.message || err.message || 'Failed to load structure')
      })
      .finally(() => setLoading(false))
  }, [expId, stage, availableStages.length])

  if (!expId) {
    return (
      <div className="h-64 flex items-center justify-center text-slate-400 bg-slate-800/50 rounded-lg">
        <div className="text-center">
          <Box className="w-12 h-12 mx-auto mb-2 opacity-30" />
          <p className="text-sm">Select an experiment to view structure</p>
        </div>
      </div>
    )
  }

  return (
    <div className={clsx(
      'bg-slate-700/30 rounded-lg overflow-hidden',
      isExpanded && 'fixed inset-4 z-50'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-slate-600">
        <div className="flex items-center gap-3">
          {/* Stage selector */}
          <select
            value={stage}
            onChange={e => setStage(e.target.value)}
            className="bg-slate-700 text-white text-sm rounded px-3 py-1.5 border border-slate-600 focus:border-blue-500 focus:outline-none"
            disabled={availableStages.length === 0}
          >
            {availableStages.length > 0 ? (
              availableStages.map(s => (
                <option key={s} value={s}>
                  {STAGE_LABELS[s] || s}
                </option>
              ))
            ) : (
              <option value="">No stages available</option>
            )}
          </select>

          {tier && (
            <span className="text-xs text-slate-400 uppercase px-2 py-1 bg-slate-700 rounded">
              {tier}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Structure info */}
          {structureInfo && (
            <div className="text-xs text-slate-400 flex items-center gap-3">
              <span>{structureInfo.n_atoms?.toLocaleString()} atoms</span>
              <span>{(structureInfo.n_bonds ?? 0).toLocaleString()} bonds</span>
              {structureInfo.density && (
                <span>{structureInfo.density.toFixed(3)} g/cm3</span>
              )}
              {structureInfo.stage !== stage && (
                <span className="text-blue-400">
                  ({STAGE_LABELS[structureInfo.stage] || structureInfo.stage})
                </span>
              )}
            </div>
          )}

          {/* Expand button */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-600 rounded"
            title={isExpanded ? 'Minimize' : 'Expand'}
          >
            {isExpanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* 3D Viewer */}
      <div className={clsx('relative', isExpanded ? 'h-[calc(100%-48px)]' : viewerHeight)}>
        {structureInfo && (structureInfo.n_bonds ?? 0) === 0 && !loading && !error && (
          <div className="absolute left-3 top-3 z-20 rounded bg-amber-500/20 px-2 py-1 text-xs text-amber-300 border border-amber-500/30">
            Bond topology unavailable in source data (0 bonds)
          </div>
        )}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-800/80 z-10">
            <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-800">
            <div className="text-center text-red-400">
              <AlertTriangle className="w-8 h-8 mx-auto mb-2" />
              <p className="text-sm">{error}</p>
            </div>
          </div>
        )}

        {structureInfo?.xyz && (
          <SimpleViewer
            xyzData={structureInfo.xyz}
            boxSize={structureInfo.box_size}
            bonds={structureInfo.bonds}
            zUp
            showAxes
            fitToFrame
          />
        )}

        {!structureInfo && !loading && !error && (
          <div className="h-full flex items-center justify-center bg-slate-800 text-slate-400">
            <div className="text-center">
              <Box className="w-12 h-12 mx-auto mb-2 opacity-30" />
              <p className="text-sm">No structure data available</p>
            </div>
          </div>
        )}
      </div>

      {/* Overlay for expanded mode */}
      {isExpanded && (
        <div
          className="fixed inset-0 bg-black/50 -z-10"
          onClick={() => setIsExpanded(false)}
        />
      )}
    </div>
  )
}
