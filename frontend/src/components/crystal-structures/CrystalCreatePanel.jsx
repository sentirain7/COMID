import clsx from 'clsx'
import { Loader2 } from 'lucide-react'
import { SimpleViewer } from '../MoleculeViewer'
import { formatSizeAngstrom, PRESET_MATERIAL_OPTIONS } from './config'
import { ElementLegend } from '../shared'

function CrystalCreatePanel({
  material,
  setMaterial,
  thickness,
  setThickness,
  hydroxylated,
  setHydroxylated,
  hydroxylDensity,
  setHydroxylDensity,
  crystalInfo,
  materialElements,
  unitPreview,
  // batch
  batchGenerateMutation,
  handleBatchGenerate,
  batchResult,
  setBatchResult,
  // preview selection
  selectedCrystalId,
  setSelectedCrystalId,
  preview,
  previewLoading,
}) {
  return (
    <div className="card p-4 space-y-4">
      {/* Controls row */}
      <div className="flex items-end gap-3 flex-wrap">
        <label className="space-y-1">
          <span className="text-xs text-slate-400">Material</span>
          <select
            className="input"
            value={material}
            onChange={(e) => { setMaterial(e.target.value); setBatchResult(null) }}
          >
            {PRESET_MATERIAL_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-slate-400">Thickness (A)</span>
          <input type="number" className="input w-24" value={thickness} min={1} step={0.1}
            onChange={(e) => setThickness(e.target.value)} />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-slate-400">OH (/nm2)</span>
          <input type="number" className="input w-20" value={hydroxylDensity}
            min={crystalInfo.ohMin || 0} max={crystalInfo.ohMax || 0} step={0.1}
            disabled={!hydroxylated || (crystalInfo.ohMax || 0) <= 0}
            onChange={(e) => setHydroxylDensity(e.target.value)} />
        </label>
        <label className={clsx(
          'inline-flex items-center gap-1.5 text-xs pb-1',
          (crystalInfo.ohMax || 0) > 0 ? 'text-slate-300' : 'text-slate-500'
        )}>
          <input type="checkbox" checked={hydroxylated}
            disabled={(crystalInfo.ohMax || 0) <= 0}
            onChange={(e) => setHydroxylated(e.target.checked)} />
          -OH
        </label>
        <button
          type="button"
          className={clsx(
            'btn py-2 px-5 text-sm font-medium',
            'bg-emerald-600/80 text-white hover:bg-emerald-600',
            batchGenerateMutation.isPending && 'opacity-80'
          )}
          disabled={batchGenerateMutation.isPending}
          onClick={handleBatchGenerate}
        >
          {batchGenerateMutation.isPending ? (
            <><Loader2 className="w-4 h-4 animate-spin inline mr-1.5" />Generating...</>
          ) : (
            'Batch All Sizes (35-60 A)'
          )}
        </button>
      </div>

      {/* Crystal info + Batch result row */}
      <div className="grid gap-3 lg:grid-cols-[4fr_6fr]">
        {/* Crystal properties + unit cell preview */}
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded border border-slate-700 bg-slate-900/40 p-2.5 space-y-1.5">
            <div className="text-sm font-medium text-slate-200">{material || 'Select material'}</div>
            {/* Common section */}
            <div className="grid grid-cols-1 gap-y-0.5 text-[11px] text-slate-400">
              <span>Name: <span className="text-slate-300">{crystalInfo.structure || '-'}</span></span>
              <span>Type: <span className="text-slate-300">{crystalInfo.system || '-'}</span></span>
              <span>Atoms: <span className="text-slate-300">{crystalInfo.nAtoms || '-'}</span></span>
              <span>Size: <span className="text-slate-300">{crystalInfo.a || '-'} × {crystalInfo.b || '-'} × {crystalInfo.c || '-'} Å</span></span>
              <span>Boundary: <span className="text-slate-300">p p f</span></span>
            </div>
            <ElementLegend elements={materialElements} />
            {/* Domain-specific section */}
            <div className="border-t border-slate-700/50 pt-1 mt-1 grid grid-cols-1 gap-y-0.5 text-[11px] text-slate-400">
              <span>Space group: <span className="text-slate-300">{crystalInfo.spaceGroup || '-'}</span></span>
              <span>Surface: <span className="text-slate-300">({crystalInfo.surface || '001'})</span></span>
              <span>gamma: <span className="text-slate-300">{crystalInfo.gamma || '-'}°</span></span>
              <span>OH: <span className="text-slate-300">
                {hydroxylated
                  ? <>{hydroxylDensity} OH/nm²</>
                  : 'Bare surface'}
                {crystalInfo.ohMax > 0 && (
                  <span className="text-slate-500 ml-1">[{crystalInfo.ohMin}~{crystalInfo.ohMax}]</span>
                )}
              </span></span>
            </div>
          </div>
          <div className="rounded border border-slate-700 overflow-hidden">
            <div className="h-full min-h-[120px] relative">
              <SimpleViewer
                xyzData={unitPreview.xyz}
                boxSize={unitPreview.boxSize}
                bonds={unitPreview.bonds}
                showAxes={false}
                zUp
                fitToFrame
                fitPadding={1.15}
                representation="ball_and_stick"
              />
            </div>
          </div>
        </div>

        {/* Batch result + generated structure preview */}
        <div className="grid grid-cols-2 gap-2">
          {/* Size grid */}
          {batchResult ? (
            <div className="rounded border border-slate-700 bg-slate-900/40 p-3 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-slate-300">
                  Generated: {batchResult.generated_count} | Skipped: {batchResult.skipped_count}
                </span>
                <span className="text-slate-500">{batchResult.surface}</span>
              </div>
              <div className="grid grid-cols-2 gap-1">
                {(batchResult.sizes || []).map((s) => {
                  const lx = s.actual_lx_angstrom || s.xy_size_angstrom || 0
                  const ly = s.actual_ly_angstrom || s.xy_size_angstrom || 0
                  const lz = s.thickness_angstrom || 0
                  return (
                    <div
                      key={s.crystal_id}
                      className={clsx(
                        'rounded border px-1.5 py-1 text-[10px] cursor-pointer transition-colors',
                        selectedCrystalId === s.crystal_id
                          ? 'border-blue-500/60 bg-blue-500/10 text-slate-200'
                          : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:bg-slate-800/70'
                      )}
                      onClick={() => setSelectedCrystalId(s.crystal_id)}
                    >
                      <div className="font-bold text-slate-200 truncate">
                        {s.name}
                      </div>
                      <div className="text-slate-400">
                        <span>{formatSizeAngstrom(lx)}x{formatSizeAngstrom(ly)}</span>
                        <span className="ml-1 text-slate-500">h={formatSizeAngstrom(lz)}</span>
                        <span className="ml-1">{Number(s.atom_count || 0).toLocaleString()}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : (
            <div className="rounded border border-dashed border-slate-600 flex items-center justify-center text-sm text-slate-500">
              {batchGenerateMutation.isPending ? 'Generating...' : 'Batch result'}
            </div>
          )}

          {/* Generated structure 3D preview */}
          {selectedCrystalId && preview?.xyz ? (
            <div className="rounded border border-slate-700 overflow-hidden">
              <div className="h-full min-h-[200px] relative">
                {previewLoading && (
                  <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-900/60 text-slate-200 text-xs">
                    Loading...
                  </div>
                )}
                <SimpleViewer
                  xyzData={preview.xyz}
                  boxSize={preview.box_size}
                  bonds={preview.bonds}
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
              {selectedCrystalId ? 'Loading preview...' : 'Select a size to preview'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default CrystalCreatePanel
