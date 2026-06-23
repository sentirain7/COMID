import { Loader2, RefreshCw, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import { SimpleViewer } from '../molecule-viewer/SimpleViewer'
import { AgingBadge, CategoryBadge, ElementLegend, EIntraCoverageBadge } from '../shared'
import { getDisplayMolTitle } from './helpers'
import { FFTypeBadge } from './MoleculeTable'
import FFStatusSection from './FFStatusSection'

/**
 * Detail / 3D preview panel for a selected molecule.
 *
 * Props:
 *   selectedMolecule  - the full molecule object (or null)
 *   previewData       - { xyz, bonds, atomCount, elements, hasFormalCharges,
 *                        formalChargeSum, ffAvailable, ffCheckMessage } or null
 *   previewLoading    - boolean
 *   previewError      - error string ('' when none)
 *   previewElements   - array of element strings for the legend
 *   representation    - 'ball_and_stick' | 'spacefill' | 'wireframe'
 *   onRepresentationChange - callback(value)
 *   onRefresh         - callback() to re-fetch structure
 */
export function MoleculePreviewPanel({
  selectedMolecule,
  previewData,
  previewLoading,
  previewError,
  previewElements,
  representation,
  onRepresentationChange,
  onRefresh,
  ffAdminRow,
  onGenerate,
  onDiagnose,
  generatingId,
}) {
  // SSOT FF status: mirror MoleculeTable's FFRouteBadge decision tree so that
  // the same molecule never reports different FF states between list & detail.
  const molRoute = selectedMolecule?.route
  let ffReady
  let ffLabel
  if (ffAdminRow) {
    const s = ffAdminRow.artifact_status
    const p = ffAdminRow.generation_profile
    const g = ffAdminRow.generator
    ffReady = s === 'complete'
    if (s === 'complete') {
      if (g === 'curated_carbon_sp2') ffLabel = 'FF Ready (Curated)'
      else if (p === 'sqm_robust') ffLabel = 'FF Ready (Robust)'
      else ffLabel = 'FF Ready'
    } else if (s === 'generating') ffLabel = 'Generating'
    else if (s === 'failed') ffLabel = 'FF Failed'
    else ffLabel = 'FF Pending'
  } else if (molRoute === 'organic_curated_artifact') {
    ffReady = false
    ffLabel = 'FF Pending'
  } else if (molRoute === 'inorganic_profile' || molRoute === 'water_model' || molRoute === 'ionic_profile') {
    // Built-in route families — FF is profile/model-based, not GAFF2 artifact.
    // previewData.ffAvailable only checks GAFF2 support, so ignore it here
    // and trust the route assignment from resolve_ff_hint (same as table badge).
    ffReady = true
    ffLabel = 'FF Ready'
  } else {
    ffReady = previewData?.ffAvailable
    ffLabel = previewData?.ffAvailable ? 'FF Ready' : 'FF Not Available'
  }

  return (
    <div className="card p-4 space-y-3 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Molecule Preview</h2>
        <div className="flex items-center gap-2">
          <select
            className="input text-xs"
            value={representation}
            onChange={(e) => onRepresentationChange(e.target.value)}
          >
            <option value="ball_and_stick">Ball and Stick</option>
            <option value="spacefill">Space Fill</option>
            <option value="wireframe">Wireframe</option>
          </select>
          {selectedMolecule && (
            <button
              type="button"
              className="p-2 rounded bg-slate-700/70 text-slate-200 hover:bg-slate-700"
              onClick={onRefresh}
              title="Refresh"
            >
              {previewLoading
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <RefreshCw className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>

      {/* No selection */}
      {!selectedMolecule && (
        <div className="text-sm text-slate-400 py-6 text-center">
          Select a molecule from the table.
        </div>
      )}

      {/* Preview content */}
      {selectedMolecule && (
        <div className="space-y-2 flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Meta: name → badges → numeric details */}
          <div className="space-y-1 text-xs">
            {/* Name — plain text */}
            <div className="text-sm font-medium text-slate-100">
              {getDisplayMolTitle(selectedMolecule)}
            </div>
            {/* Badges row */}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              {selectedMolecule.display_category && (
                <CategoryBadge category={selectedMolecule.display_category} />
              )}
              <FFTypeBadge mol={selectedMolecule} adminRow={ffAdminRow} />
              {previewData && !previewLoading && (
                <span
                  className={clsx(
                    'inline-flex items-center justify-center w-20 px-1.5 py-0.5 rounded text-[10px] border',
                    ffReady
                      ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-400'
                      : 'bg-amber-500/15 border-amber-500/40 text-amber-400'
                  )}
                  title={previewData.ffCheckMessage || ''}
                >
                  {ffLabel}
                </span>
              )}
              {previewData?.hasFormalCharges && !previewLoading && (
                <span className="inline-flex items-center justify-center px-1.5 py-0.5 rounded text-[10px] border bg-blue-500/15 border-blue-500/40 text-blue-400">
                  Ionic (q={previewData.formalChargeSum > 0 ? '+' : ''}{previewData.formalChargeSum.toFixed(1)})
                </span>
              )}
              {selectedMolecule.e_intra_coverage && previewData && !previewLoading && (
                <EIntraCoverageBadge coverage={selectedMolecule.e_intra_coverage} />
              )}
            </div>
            {/* Numeric details */}
            <div className="flex flex-wrap items-center gap-x-3 text-slate-400">
              {previewData?.atomCount > 0 && (
                <span>{previewData.atomCount.toLocaleString()} atoms</span>
              )}
              {previewData?.bonds?.length > 0 && (
                <span>{previewData.bonds.length.toLocaleString()} bonds</span>
              )}
              {selectedMolecule.molecular_weight && (
                <span>{selectedMolecule.molecular_weight.toFixed(2)} g/mol</span>
              )}
            </div>
          </div>

          {/* Element legend — compact single line */}
          {previewElements.length > 0 && <ElementLegend elements={previewElements} />}

          {/* 3D viewer */}
          <div className="flex-1 min-h-[240px] relative rounded border border-slate-700 overflow-hidden">
            {previewError && (
              <div className={clsx(
                "absolute top-2 left-2 right-2 z-10 rounded px-3 py-2 flex items-center gap-2 text-sm",
                previewError.includes('not found')
                  ? 'bg-amber-500/15 border border-amber-500/30 text-amber-300'
                  : 'bg-red-500/15 border border-red-500/30 text-red-300'
              )}>
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span>
                  {previewError.includes('not found')
                    ? 'This molecule has no structure file for that aging state (using Non-Aging reference)'
                    : previewError}
                </span>
              </div>
            )}
            {!previewError && previewData?.xyz && (
              <SimpleViewer
                xyzData={previewData.xyz}
                bonds={previewData.bonds}
                fitToFrame
                fitPadding={0.72}
                representation={representation}
              />
            )}
            {previewLoading && !previewData?.xyz && (
              <div className="absolute inset-0 flex items-center justify-center">
                <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
              </div>
            )}
            {!previewLoading && !previewError && !previewData?.xyz && (
              <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-xs">
                No structure data available
              </div>
            )}
          </div>

          {ffAdminRow && (
            <div className="flex-shrink-0 mt-auto min-h-0">
              <FFStatusSection
                row={ffAdminRow}
                molId={selectedMolecule.mol_id}
                onGenerate={onGenerate}
                onDiagnose={onDiagnose}
                generatingId={generatingId}
              />
            </div>
          )}

          {/* P1.5: Aging Artifact Status Section — only for organic_curated_artifact */}
          {selectedMolecule?.route === 'organic_curated_artifact' &&
            selectedMolecule?.aging_artifact_status && (
              <div className="flex-shrink-0 border-t border-slate-700 pt-2 space-y-1">
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
                  Aging Variants
                </h4>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(selectedMolecule.aging_artifact_status).map(
                    ([aging, status]) => {
                      // Skip not_applicable entries
                      if (status.status === 'not_applicable') return null
                      return (
                        <AgingBadge
                          key={aging}
                          agingState={aging}
                          artifactReady={status.ready}
                          sourceId={status.source_id}
                          showArtifactIcon
                        />
                      )
                    }
                  )}
                </div>
                {/* Shared source indicator */}
                {selectedMolecule.aging_artifact_status.non_aging?.source_id && (
                  <div className="text-[10px] text-slate-500">
                    Shared source: {selectedMolecule.aging_artifact_status.non_aging.source_id}
                  </div>
                )}
              </div>
            )}

          {!ffAdminRow && selectedMolecule && (
            <div className="flex-shrink-0 mt-auto min-h-0 border-t border-slate-700 pt-2 space-y-1">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide"
                    title={selectedMolecule.ff_display_label || ''}>
                  FF Parameters
                </h4>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                {selectedMolecule.route && (
                  <div className="truncate" title={selectedMolecule.route}>
                    <span className="text-slate-400">Route: </span>
                    <span className="text-slate-300">{selectedMolecule.route}</span>
                  </div>
                )}
                {selectedMolecule.status && (
                  <div className="truncate" title={selectedMolecule.status}>
                    <span className="text-slate-400">Status: </span>
                    <span className="text-slate-300">{selectedMolecule.status}</span>
                  </div>
                )}
                {selectedMolecule.parameterization_mode && (
                  <div className="truncate" title={selectedMolecule.parameterization_mode}>
                    <span className="text-slate-400">Mode: </span>
                    <span className="text-slate-300">{selectedMolecule.parameterization_mode}</span>
                  </div>
                )}
                {selectedMolecule.submit_ff_type && (
                  <div className="truncate" title={selectedMolecule.submit_ff_type}>
                    <span className="text-slate-400">Submit: </span>
                    <span className="text-slate-300">{selectedMolecule.submit_ff_type}</span>
                  </div>
                )}
                {selectedMolecule.ff_hint && (
                  <div className="truncate" title={selectedMolecule.ff_hint}>
                    <span className="text-slate-400">Hint: </span>
                    <span className="text-slate-300">{selectedMolecule.ff_hint}</span>
                  </div>
                )}
                {previewData?.ffCheckMessage && !previewLoading && (
                  <div className="truncate col-span-2 text-slate-500"
                       title={previewData.ffCheckMessage}>
                    {previewData.ffCheckMessage}
                  </div>
                )}
                {selectedMolecule.artifact_warning && (
                  <div className="text-amber-400 col-span-2 truncate"
                       title={selectedMolecule.artifact_warning}>
                    {selectedMolecule.artifact_warning}
                  </div>
                )}
                {selectedMolecule.blocked_reason && (
                  <div className="text-red-400 col-span-2 truncate"
                       title={selectedMolecule.blocked_reason}>
                    Blocked: {selectedMolecule.blocked_reason}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
