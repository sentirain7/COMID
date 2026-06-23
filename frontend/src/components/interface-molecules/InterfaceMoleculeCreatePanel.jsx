import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { Loader2 } from 'lucide-react'
import { SimpleViewer } from '../MoleculeViewer'
import { ElementLegend } from '../shared'
import { useInterfaceMoleculePreview } from '../../hooks/useApiInterfaceMolecules'
import {
  INTERFACE_MOLECULE_INFO,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  BATCH_XY_DEFAULTS,
} from './config'

function pickPreferredMolecule(molecules, category) {
  const inCat = (molecules || []).filter(
    (m) => INTERFACE_MOLECULE_INFO[m.mol_id]?.category === category
  )
  return inCat.find((m) => m.generation_supported !== false) || inCat[0] || null
}

function InterfaceMoleculeCreatePanel({
  molecules,
  loading,
  selectedMolId,
  setSelectedMolId,
  // Batch generation
  batchGenerateMutation,
  handleBatchGenerate,
  batchResult,
  setBatchResult,
  // Cell preview (reuse existing from parent)
  selectedCellId,
  setSelectedCellId,
  cellPreview,
  cellPreviewLoading,
}) {
  const [category, setCategory] = useState('deicing')
  const [lz, setLz] = useState(BATCH_XY_DEFAULTS.lz_default)
  const [density, setDensity] = useState(1.0)

  // Get molecule preview
  const { data: molPreview, loading: molPreviewLoading } = useInterfaceMoleculePreview(
    selectedMolId,
    Boolean(selectedMolId)
  )

  const molInfo = useMemo(
    () => INTERFACE_MOLECULE_INFO[selectedMolId] || {},
    [selectedMolId]
  )

  const selectedMolData = useMemo(
    () => molecules?.find((m) => m.mol_id === selectedMolId),
    [molecules, selectedMolId]
  )

  // Filter molecules by category
  const filteredMolecules = useMemo(() => {
    if (!molecules) return []
    return molecules.filter((m) => {
      const info = INTERFACE_MOLECULE_INFO[m.mol_id]
      return info && info.category === category
    })
  }, [molecules, category])

  // Handle molecule selection - update density default and clear batch
  const handleMoleculeSelect = (molId) => {
    setSelectedMolId(molId)
    const apiMol = molecules?.find((m) => m.mol_id === molId)
    const configInfo = INTERFACE_MOLECULE_INFO[molId]
    setDensity(apiMol?.recommended_density || configInfo?.defaultDensity || 1.0)
    setBatchResult(null)
  }

  // Auto-select first supported molecule on initial load
  useEffect(() => {
    if (molecules?.length && !selectedMolId) {
      const mol = pickPreferredMolecule(molecules, category)
      if (mol) handleMoleculeSelect(mol.mol_id)
    }
  }, [molecules]) // eslint-disable-line react-hooks/exhaustive-deps

  // Handle category change - auto-select first supported molecule in new category
  const handleCategoryChange = (cat) => {
    setCategory(cat)
    setBatchResult(null)
    const mol = pickPreferredMolecule(molecules, cat)
    if (mol) handleMoleculeSelect(mol.mol_id)
  }

  // Detect unsupported molecules
  const currentMolSupported = useMemo(() => {
    if (!selectedMolId || !molecules) return true
    const mol = molecules.find((m) => m.mol_id === selectedMolId)
    return mol?.generation_supported !== false
  }, [selectedMolId, molecules])

  const currentMolReason = useMemo(() => {
    if (!selectedMolId || !molecules) return null
    const mol = molecules.find((m) => m.mol_id === selectedMolId)
    return mol?.generation_reason || null
  }, [selectedMolId, molecules])

  // Handle lz/density change - clear batch result
  const handleLzChange = (val) => {
    setLz(val)
    setBatchResult(null)
  }

  const handleDensityChange = (val) => {
    setDensity(val)
    setBatchResult(null)
  }

  // Handle batch generate
  const onBatchClick = () => {
    if (!selectedMolId) return
    handleBatchGenerate({
      mol_id: selectedMolId,
      xy_min: BATCH_XY_DEFAULTS.xy_min,
      xy_max: BATCH_XY_DEFAULTS.xy_max,
      lz_angstrom: lz,
      target_density: density,
      boundary_mode: 'ppf',
    })
  }

  return (
    <div className="card p-4 space-y-4">
      {/* Upper section: Category tabs + Molecule grid + Controls */}
      <div className="space-y-3">
        {/* Category tabs */}
        <div className="flex gap-2 flex-wrap">
          {CATEGORY_ORDER.map((cat) => (
            <button
              key={cat}
              type="button"
              className={clsx(
                'px-3 py-1 text-xs rounded-lg transition-colors',
                category === cat
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700/50 text-slate-400 hover:bg-slate-700'
              )}
              onClick={() => handleCategoryChange(cat)}
            >
              {CATEGORY_LABELS[cat]}
            </button>
          ))}
        </div>

        {/* Molecule grid */}
        <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
          {loading ? (
            <div className="col-span-full text-center text-slate-500 py-4">
              <Loader2 className="w-5 h-5 animate-spin inline" />
            </div>
          ) : filteredMolecules.length === 0 ? (
            <div className="col-span-full text-center text-slate-500 py-4">
              No molecules in this category
            </div>
          ) : (
            filteredMolecules.map((mol) => {
              const info = INTERFACE_MOLECULE_INFO[mol.mol_id] || {}
              return (
                <button
                  key={mol.mol_id}
                  type="button"
                  className={clsx(
                    'p-2 rounded border text-left transition-colors',
                    selectedMolId === mol.mol_id
                      ? 'border-blue-500 bg-blue-500/10'
                      : 'border-slate-700 bg-slate-800/50 hover:border-slate-600',
                    mol.generation_supported === false && 'opacity-50'
                  )}
                  onClick={() => handleMoleculeSelect(mol.mol_id)}
                >
                  <div className="text-sm font-medium text-slate-200">{info.formula}</div>
                  <div className="text-[10px] text-slate-500 truncate">{info.name}</div>
                </button>
              )
            })
          )}
        </div>

        {/* Controls row */}
        <div className="flex items-end gap-3 flex-wrap">
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Thickness (lz)</span>
            <input
              type="number"
              className="input w-20"
              value={lz}
              min={5}
              step={5}
              onChange={(e) => handleLzChange(Number(e.target.value))}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Density (g/cm3)</span>
            <input
              type="number"
              className="input w-24"
              value={density}
              min={0.1}
              max={5}
              step={0.1}
              onChange={(e) => handleDensityChange(Number(e.target.value))}
            />
          </label>
          <div className="space-y-1">
            <button
              type="button"
              className={clsx(
                'btn py-2 px-5 text-sm font-medium',
                'bg-emerald-600/80 text-white hover:bg-emerald-600',
                batchGenerateMutation?.isPending && 'opacity-80'
              )}
              disabled={batchGenerateMutation?.isPending || !selectedMolId || !currentMolSupported}
              onClick={onBatchClick}
            >
              {batchGenerateMutation?.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin inline mr-1.5" />
                  Generating...
                </>
              ) : (
                `Batch All Sizes (${BATCH_XY_DEFAULTS.xy_min}-${BATCH_XY_DEFAULTS.xy_max} A)`
              )}
            </button>
            {!currentMolSupported && currentMolReason && (
              <div className="text-xs text-amber-400 mt-1">
                Not supported: {currentMolReason}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Lower section: Crystal-style 2-column layout */}
      <div className="grid gap-3 lg:grid-cols-[4fr_6fr]">
        {/* Left: Molecule Info + Unit Preview (2x1) */}
        <div className="grid grid-cols-2 gap-2">
          {/* Molecule Info Card */}
          <div className="rounded border border-slate-700 bg-slate-900/40 p-2.5 space-y-1.5">
            {molInfo.formula ? (
              <>
                <div className="text-sm font-medium text-slate-200">{molInfo.formula}</div>
                {/* Common section */}
                <div className="grid grid-cols-1 gap-y-0.5 text-[11px] text-slate-400">
                  <span>Name: <span className="text-slate-300">{molInfo.name}</span></span>
                  <span>Type: <span className="text-slate-300">{CATEGORY_LABELS[molInfo.category]}</span></span>
                  <span>Atoms: <span className="text-slate-300">{molInfo.atoms}</span></span>
                  <span>Size: <span className="text-slate-300">
                    {selectedMolData?.mol_size_angstrom
                      ? `${selectedMolData.mol_size_angstrom[0]?.toFixed(1)} × ${selectedMolData.mol_size_angstrom[1]?.toFixed(1)} × ${selectedMolData.mol_size_angstrom[2]?.toFixed(1)} Å`
                      : '\u2014'}
                  </span></span>
                  <span>Boundary: <span className="text-slate-300">p p f</span></span>
                </div>
                <ElementLegend elements={molInfo.elements} />
                {/* Domain-specific section */}
                <div className="border-t border-slate-700/50 pt-1 mt-1 grid grid-cols-1 gap-y-0.5 text-[11px] text-slate-400">
                  <span>MW: <span className="text-slate-300">{molInfo.mw?.toFixed(2)} g/mol</span></span>
                  <span>Density: <span className="text-slate-300">{density.toFixed(2)} g/cm³</span></span>
                  <span>Max extent: <span className="text-slate-300">
                    {selectedMolData?.max_extent_angstrom != null
                      ? `${selectedMolData.max_extent_angstrom.toFixed(1)} Å`
                      : '\u2014'}
                  </span></span>
                </div>
              </>
            ) : (
              <div className="text-xs text-slate-500 py-4 text-center">
                Select a molecule
              </div>
            )}
          </div>

          {/* Unit Molecule Preview */}
          <div className="rounded border border-slate-700 overflow-hidden">
            <div className="h-full min-h-[120px] relative">
              {molPreviewLoading ? (
                <div className="absolute inset-0 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
                </div>
              ) : molPreview?.xyz ? (
                <SimpleViewer
                  xyzData={molPreview.xyz}
                  bonds={molPreview.bonds}
                  showAxes={false}
                  fitToFrame
                  fitPadding={1.15}
                  representation="ball_and_stick"
                />
              ) : (
                <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-xs">
                  Unit molecule
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Batch Result + Generated Preview (2x1) */}
        <div className="grid grid-cols-2 gap-2">
          {/* Batch Result Grid */}
          {batchResult ? (
            <div className="rounded border border-slate-700 bg-slate-900/40 p-3 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-slate-300">
                  Generated: {batchResult.generated_count} | Skipped: {batchResult.skipped_count}{batchResult.failed_count > 0 && ` | Failed: ${batchResult.failed_count}`}
                </span>
                <span className="text-slate-500">{batchResult.mol_name}</span>
              </div>
              {batchResult.failures?.length > 0 && (
                <div className="text-xs text-amber-400 mt-1">
                  {batchResult.failures[0].message}
                  {batchResult.failures.length > 1 && ` (+${batchResult.failures.length - 1} more)`}
                </div>
              )}
              <div className="grid grid-cols-2 gap-1">
                {(batchResult.cells || []).map((cell) => (
                  <div
                    key={cell.cell_id}
                    className={clsx(
                      'rounded border px-1.5 py-1 text-[10px] cursor-pointer transition-colors',
                      selectedCellId === cell.cell_id
                        ? 'border-blue-500/60 bg-blue-500/10 text-slate-200'
                        : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:bg-slate-800/70'
                    )}
                    onClick={() => setSelectedCellId(cell.cell_id)}
                  >
                    <div className="font-bold text-slate-200">
                      {cell.lx_angstrom}x{cell.ly_angstrom}
                    </div>
                    <div className="text-slate-400">
                      <span>h={cell.lz_angstrom}</span>
                      <span className="ml-1">{cell.atom_count} atoms</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded border border-dashed border-slate-600 flex items-center justify-center text-sm text-slate-500">
              {batchGenerateMutation?.isPending ? 'Generating...' : 'Batch result'}
            </div>
          )}

          {/* Generated Cell 3D Preview */}
          {selectedCellId && cellPreview?.xyz ? (
            <div className="rounded border border-slate-700 overflow-hidden">
              <div className="h-full min-h-[200px] relative">
                {cellPreviewLoading && (
                  <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-900/60 text-slate-200 text-xs">
                    Loading...
                  </div>
                )}
                <SimpleViewer
                  xyzData={cellPreview.xyz}
                  boxSize={cellPreview.box_size}
                  bonds={cellPreview.bonds}
                  showAxes
                  zUp
                  fitToFrame
                  fitPadding={0.8}
                  representation="ball_and_stick"
                />
              </div>
            </div>
          ) : (
            <div className="rounded border border-dashed border-slate-600 flex items-center justify-center text-sm text-slate-500 min-h-[200px]">
              {selectedCellId ? 'Loading preview...' : 'Select a size to preview'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default InterfaceMoleculeCreatePanel
