import { useEffect, useMemo, useState } from 'react'
import { Loader2, Trash2, RefreshCw, AlertCircle, Search } from 'lucide-react'
import clsx from 'clsx'
import { useQueryClient } from '@tanstack/react-query'
import { useLayeredExperiments, useStressStrainCurve } from '../hooks/useApiLayeredStructures'
import { useArrayMetricData } from '../hooks/useApi'
import { useBatchDeleteExperiments } from '../hooks/useApiExperiments'
import { MoleculeViewer } from './MoleculeViewer'
import ThermoChart from './ThermoChart'
import StressStrainChart from './Charts/StressStrainChart'
import PageHeader from './shared/PageHeader'
import {
  HEADER_ACTION_BUTTON,
} from './shared/headerActionStyles'
import ScanDatabaseModal from './ScanDatabaseModal'
import { ROUTE_KEYS } from '../navigation/routeMeta'
import {
  getEIntraMethodLabel,
  getEIntraMethodShortLabel,
} from '../lib/eIntraMethod'

const fmt = (v, d = 1) => (v != null ? Number(v).toFixed(d) : '-')
const fmtSize = (lx, ly, lz) =>
  lx != null && ly != null && lz != null
    ? `${Number(lx).toFixed(0)}\u00D7${Number(ly).toFixed(0)}\u00D7${Number(lz).toFixed(0)}`
    : '-'

const layerSummary = (layers) => {
  if (!layers?.length) return '-'
  return layers.map((l) => l.label || l.source_type?.replace('_', ' ') || '?').join(' / ')
}

const STATUS_BADGE = {
  completed: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  failed: 'bg-red-500/20 text-red-400 border-red-500/30',
  running: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
}

const METRIC_CARDS = [
  { key: 'tensile_strength', label: 'Tensile Str.', unit: 'MPa', digits: 1 },
  { key: 'elastic_modulus', label: 'E-Modulus', unit: 'GPa', digits: 2 },
  { key: 'adhesion_energy', label: 'Adhesion', unit: 'mJ/m\u00B2', digits: 1 },
  { key: 'toughness', label: 'Toughness', unit: 'MJ/m\u00B3', digits: 2 },
  { key: 'work_of_separation', label: 'W_sep', unit: 'mJ/m\u00B2', digits: 1 },
  { key: 'ductility', label: 'Ductility', unit: '', digits: 3 },
]

export default function LayeredStructureLibrary() {
  const { data, loading, error, execute } = useLayeredExperiments({ limit: 200 })
  const deleteMutation = useBatchDeleteExperiments()
  const queryClient = useQueryClient()

  const [selected, setSelected] = useState(new Set())
  const [activeExpId, setActiveExpId] = useState(null)
  const [scanModalOpen, setScanModalOpen] = useState(false)

  const items = useMemo(() => data?.items || [], [data])

  // Auto-select first row
  useEffect(() => {
    if (items.length > 0 && !activeExpId) setActiveExpId(items[0].exp_id)
  }, [items, activeExpId])

  const activeItem = useMemo(() => items.find((it) => it.exp_id === activeExpId), [items, activeExpId])

  // Lazy fetch for selected experiment — expose loading + error
  const { data: ssData, loading: ssLoading, error: ssError } = useStressStrainCurve(activeExpId)
  const {
    data: cedProfileData,
    loading: cedProfileLoading,
    error: cedProfileError,
  } = useArrayMetricData(activeExpId, 'cohesive_energy_density_profile')

  const profileRows = useMemo(() => {
    if (!cedProfileData?.columns) return []
    const indices = cedProfileData.columns.layer_index || []
    const labels = cedProfileData.columns.layer_label || []
    const cedValues = cedProfileData.columns.ced_MJ_m3 || []
    const volumes = cedProfileData.columns.volume_A3 || []
    return indices.map((index, idx) => ({
      layerIndex: index,
      layerLabel: labels[idx] ?? `layer_${index}`,
      cedMJm3: cedValues[idx] ?? null,
      volumeA3: volumes[idx] ?? null,
    }))
  }, [cedProfileData])

  const storedProfileMethod = cedProfileData?.metadata?.e_intra_method || null

  const toggleSelect = (expId) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(expId) ? next.delete(expId) : next.add(expId)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === items.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(items.map((it) => it.exp_id)))
    }
  }

  const handleBulkDelete = async () => {
    if (selected.size === 0) return
    if (!window.confirm(`Delete ${selected.size} layered experiment(s)?`)) return
    try {
      await deleteMutation.mutateAsync([...selected])
      queryClient.invalidateQueries({ queryKey: ['layered-experiments'] })
      setSelected(new Set())
      if (selected.has(activeExpId)) setActiveExpId(null)
    } catch (e) {
      console.error('Bulk delete failed:', e)
    }
  }

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col">
      <PageHeader routeKey={ROUTE_KEYS.LAYERED_STRUCTURES_DATABASE}>
        <div className="flex items-center gap-2">
          <button
            className={HEADER_ACTION_BUTTON}
            onClick={execute}
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button
            className={HEADER_ACTION_BUTTON}
            onClick={() => setScanModalOpen(true)}
          >
            <Search className="w-4 h-4" />
            Scan Database
          </button>
        </div>
      </PageHeader>
      <ScanDatabaseModal
        open={scanModalOpen}
        onClose={() => { setScanModalOpen(false); execute() }}
      />

      {/* Responsive: stack on small screens, side-by-side on md+ */}
      <div className="flex-1 flex flex-col md:flex-row gap-3 min-h-0 p-3 pt-0">
        {/* Left: Table */}
        <div className="w-full md:w-[55%] flex flex-col min-h-0 rounded-lg border border-slate-700 bg-slate-800/30">
          {/* Toolbar */}
          <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-700 text-xs">
            <span className="text-slate-400">{items.length} experiments</span>
          </div>

          {/* Table */}
          <div className="flex-1 overflow-auto min-h-[200px]">
            {loading ? (
              <div className="flex justify-center py-8"><Loader2 className="animate-spin text-slate-500" size={20} /></div>
            ) : error ? (
              <div className="text-red-400 text-xs p-4">{String(error)}</div>
            ) : items.length === 0 ? (
              <div className="text-slate-500 text-xs p-4 text-center">No completed layered experiments</div>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-800/90 z-10">
                  <tr className="text-slate-400 border-b border-slate-700 text-center">
                    <th className="w-8 px-2 py-1.5">
                      <input type="checkbox" checked={selected.size === items.length && items.length > 0} onChange={toggleAll} className="accent-blue-500" />
                    </th>
                    <th className="w-8 px-2 py-1.5">#</th>
                    <th className="px-2 py-1.5">Name</th>
                    <th className="px-2 py-1.5">Layers</th>
                    <th className="px-2 py-1.5">Status</th>
                    <th className="px-2 py-1.5">T (K)</th>
                    <th className="px-2 py-1.5 hidden sm:table-cell">Size (A)</th>
                    <th className="px-2 py-1.5 hidden lg:table-cell">Tensile</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it, index) => (
                    <tr
                      key={it.exp_id}
                      className={clsx(
                        'border-b border-slate-700/50 cursor-pointer transition-colors text-center',
                        activeExpId === it.exp_id ? 'bg-blue-500/10' : 'hover:bg-slate-700/30'
                      )}
                      onClick={() => setActiveExpId(it.exp_id)}
                    >
                      <td className="px-2 py-1.5" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selected.has(it.exp_id)} onChange={() => toggleSelect(it.exp_id)} className="accent-blue-500" />
                      </td>
                      <td className="px-2 py-1.5 text-[10px] text-slate-500 font-mono">{index + 1}</td>
                      <td className="px-2 py-1.5 text-slate-200 truncate max-w-[160px]" title={it.exp_id}>{it.name}</td>
                      <td className="px-2 py-1.5 text-slate-400 truncate max-w-[140px]" title={layerSummary(it.layers)}>
                        {layerSummary(it.layers)}
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex justify-center">
                          <span className={clsx('px-1.5 py-0.5 rounded text-[10px] border', STATUS_BADGE[it.status] || 'bg-slate-700 text-slate-400 border-slate-600')}>
                            {it.status}
                          </span>
                        </div>
                      </td>
                      <td className="px-2 py-1.5 text-slate-300">{fmt(it.temperature_K, 0)}</td>
                      <td className="px-2 py-1.5 text-slate-400 hidden sm:table-cell">{fmtSize(it.box_lx, it.box_ly, it.box_lz)}</td>
                      <td className="px-2 py-1.5 text-slate-300 hidden lg:table-cell">{it.tensile_strength != null ? `${fmt(it.tensile_strength)} MPa` : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right: Detail panel — no overflow-auto so height matches left table */}
        <div className="w-full md:w-[45%] flex flex-col min-h-0 gap-4">
          {/* Header card — always visible */}
          <div className="rounded-lg border border-slate-700 bg-slate-800/30 px-4 py-3">
            <div className="text-sm font-semibold text-slate-200">Experiment Detail</div>
          </div>

          {!activeItem && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/30 flex items-center justify-center text-slate-500 text-sm py-6">
              Select an experiment from the table.
            </div>
          )}

          {activeItem && (
            <>
              {/* 3D Viewer (left half) + Layers & Metrics (right half) */}
              <div className="flex gap-4">
                {/* 3D Viewer — 50% width, taller */}
                <div className="w-1/2 rounded-lg border border-slate-700 bg-slate-800/30 p-4 flex flex-col">
                  <div className="text-sm font-semibold text-slate-300 mb-3">3D Structure</div>
                  <div className="flex-1 flex items-center justify-center">
                    <MoleculeViewer expId={activeExpId} viewerHeight="h-64" />
                  </div>
                </div>

                {/* Layers + Mechanical Properties — 50% width */}
                <div className="w-1/2 flex flex-col gap-4">
                  {/* Layer info */}
                  {activeItem.layers && activeItem.layers.length > 0 && (
                    <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
                      <div className="text-sm font-semibold text-slate-300 mb-3">Layers ({activeItem.layer_count})</div>
                      <div className="space-y-1">
                        {activeItem.layers.map((l) => (
                          <div key={l.layer_index} className="flex items-center gap-1.5 text-[10px]">
                            <span className="w-4 text-right text-slate-500">{l.layer_index}</span>
                            <span className="px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-300">
                              {l.label || l.source_type?.replace('_', ' ')}
                            </span>
                            {l.source_id && (
                              <span className="text-slate-500 truncate max-w-[120px]" title={l.source_id}>
                                {l.source_id}
                              </span>
                            )}
                            {l.gap_after_angstrom != null && l.gap_after_angstrom > 0 && (
                              <span className="text-slate-600">gap {l.gap_after_angstrom} A</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Metric cards */}
                  <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4 flex-1">
                    <div className="text-sm font-semibold text-slate-300 mb-3">Mechanical Properties</div>
                    <div className="grid grid-cols-2 gap-1.5">
                      {METRIC_CARDS.map((mc) => (
                        <div key={mc.key} className="rounded bg-slate-700/40 px-2 py-1">
                          <div className="text-[10px] text-slate-400">{mc.label}</div>
                          <div className="text-sm font-medium text-slate-200">
                            {activeItem[mc.key] != null ? `${Number(activeItem[mc.key]).toFixed(mc.digits)}` : '-'}
                            {activeItem[mc.key] != null && mc.unit && <span className="text-[10px] text-slate-400 ml-0.5">{mc.unit}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <div className="text-sm font-semibold text-slate-300">
                        Layered CED Profile
                      </div>
                      {storedProfileMethod && (
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] border bg-blue-500/10 border-blue-500/40 text-blue-300"
                          title={getEIntraMethodLabel(storedProfileMethod)}
                        >
                          {getEIntraMethodShortLabel(storedProfileMethod)}
                        </span>
                      )}
                    </div>
                    {cedProfileLoading ? (
                      <div className="flex justify-center py-4">
                        <Loader2 className="animate-spin text-slate-500" size={14} />
                      </div>
                    ) : cedProfileError ? (
                      /not found|no .*data/i.test(String(cedProfileError)) ? (
                        <div className="text-[10px] text-slate-500 py-3 text-center">
                          No layer-resolved CED profile for this experiment
                        </div>
                      ) : (
                        <div className="text-[10px] text-amber-400 py-3 text-center">
                          Failed to load layer profile: {String(cedProfileError)}
                        </div>
                      )
                    ) : profileRows.length > 0 ? (
                      <div className="overflow-x-auto">
                        <table className="w-full text-[10px]">
                          <thead>
                            <tr className="border-b border-slate-700 text-slate-400">
                              <th className="py-1 text-left">Layer</th>
                              <th className="py-1 text-right">CED</th>
                              <th className="py-1 text-right">Vol.</th>
                            </tr>
                          </thead>
                          <tbody>
                            {profileRows.map((row) => (
                              <tr key={row.layerLabel} className="border-b border-slate-800 text-slate-300">
                                <td className="py-1 pr-2">
                                  <div className="flex flex-col">
                                    <span>{row.layerLabel}</span>
                                    <span className="text-slate-500">#{row.layerIndex}</span>
                                  </div>
                                </td>
                                <td className="py-1 text-right font-mono">
                                  {row.cedMJm3 != null ? Number(row.cedMJm3).toFixed(2) : '-'}
                                  {row.cedMJm3 != null && (
                                    <span className="ml-1 text-[9px] text-slate-500">MJ/m³</span>
                                  )}
                                </td>
                                <td className="py-1 text-right font-mono text-slate-400">
                                  {row.volumeA3 != null ? Number(row.volumeA3).toFixed(1) : '-'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="text-[10px] text-slate-500 py-3 text-center">
                        No layer-resolved CED profile for this experiment
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Stress-Strain Chart — flex-1 fills remaining space to align bottom with left table */}
              <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4 flex-1 min-h-[120px] flex flex-col">
                <div className="text-sm font-semibold text-slate-300 mb-3">Stress-Strain Curve</div>
                {ssLoading ? (
                  <div className="flex justify-center py-6"><Loader2 className="animate-spin text-slate-500" size={16} /></div>
                ) : ssError ? (
                  /not found|no stress/i.test(String(ssError)) ? (
                    <div className="text-[10px] text-slate-500 py-6 text-center">No stress-strain data for this experiment</div>
                  ) : (
                    <div className="flex items-center gap-1.5 text-[10px] text-amber-400 py-4 justify-center">
                      <AlertCircle size={12} />
                      Error loading data: {String(ssError)}
                    </div>
                  )
                ) : ssData ? (
                  <div className="flex-1">
                    <StressStrainChart strain={ssData.strain} stressMPa={ssData.stress_MPa} peakIndex={ssData.peak_index} />
                  </div>
                ) : (
                  <div className="text-[10px] text-slate-500 py-6 text-center flex-1 flex items-center justify-center">No stress-strain data available</div>
                )}
              </div>

              {/* Thermo Chart — fixed height for ResponsiveContainer stability */}
              <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4 h-[280px] shrink-0">
                <div className="text-sm font-semibold text-slate-300 mb-3">Thermodynamic History</div>
                <ThermoChart expId={activeExpId} />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Fixed bottom selection action bar */}
      {selected.size > 0 && (
        <div className="fixed bottom-0 left-72 right-0 z-40 flex items-center gap-3 px-4 py-2.5 bg-slate-800 border-t border-slate-700">
          <span className="text-xs text-slate-300">{selected.size} selected</span>
          <button
            onClick={handleBulkDelete}
            disabled={deleteMutation.isPending}
            className="px-3 py-1 rounded text-xs font-medium bg-red-600 hover:bg-red-700 text-white flex items-center gap-1"
          >
            <Trash2 size={12} />
            Delete Selected
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-200"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}
