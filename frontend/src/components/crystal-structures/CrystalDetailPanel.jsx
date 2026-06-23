import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import { SimpleViewer } from '../molecule-viewer/SimpleViewer'
import { ElementLegend } from '../shared'
import { formatTransformationMatrix, formatErrorPct } from './utils'

function CrystalDetailPanel({
  selectedCrystalId,
  selectedCrystal,
  preview,
  previewLoading,
  previewErrorMessage,
  previewAtomTypes,
  representation,
  setRepresentation,
  refreshPreview,
  libraryCellMetrics,
}) {
  const selectedMatrixLabel = formatTransformationMatrix(selectedCrystal?.transformation_matrix)

  return (
    <div className="card p-4 space-y-3 sticky top-0 self-start">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Generated Structure</h2>
        <div className="flex items-center gap-2">
          <select
            className="input text-xs"
            value={representation}
            onChange={(e) => setRepresentation(e.target.value)}
          >
            <option value="ball_and_stick">Ball and Stick</option>
            <option value="spacefill">Space Fill</option>
            <option value="wireframe">Wireframe</option>
          </select>
          {selectedCrystalId && (
            <button
              type="button"
              className="p-2 rounded bg-slate-700/70 text-slate-200 hover:bg-slate-700"
              onClick={() => refreshPreview()}
              title="Refresh"
            >
              {previewLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>

      {!selectedCrystalId && (
        <div className="text-sm text-slate-400 py-6 text-center">
          Select a crystal from the table or batch result.
        </div>
      )}

      {selectedCrystalId && (
        <div className="space-y-3">
          {/* Info badges */}
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
            <span className="px-2 py-1 rounded bg-slate-700/70 font-medium">
              {selectedCrystal?.material}
              <span className="text-slate-500 ml-1">({selectedCrystal?.surface})</span>
            </span>
            {preview?.n_atoms > 0 && <span>{preview.n_atoms.toLocaleString()} atoms</span>}
            {preview?.n_bonds > 0 && <span>{preview.n_bonds.toLocaleString()} bonds</span>}
            {preview?.density != null && <span>{preview.density.toFixed(3)} g/cm3</span>}
          </div>

          {/* Cell dimensions */}
          {libraryCellMetrics.lx != null && (
            <div className="text-xs text-slate-300 grid grid-cols-2 gap-x-3 gap-y-0.5">
              <span>lx: {libraryCellMetrics.lx.toFixed(2)} A</span>
              <span>ly: {libraryCellMetrics.ly.toFixed(2)} A</span>
              <span>lz: {libraryCellMetrics.lz.toFixed(2)} A</span>
              <span>V: {libraryCellMetrics.volume.toFixed(1)} A^3</span>
            </div>
          )}

          {/* Supercell metadata */}
          {(selectedCrystal?.matrix_search_used || selectedCrystal?.n_cells_xy) && (
            <div className="text-xs text-slate-400 space-y-0.5">
              {selectedMatrixLabel && <div>Matrix: {selectedMatrixLabel}</div>}
              {selectedCrystal?.n_cells_xy != null && (
                <div>det={selectedCrystal.n_cells_xy}, nz={selectedCrystal?.nz ?? '-'}, err={formatErrorPct(selectedCrystal?.error_xy_pct)}</div>
              )}
            </div>
          )}

          {/* Element legend */}
          {previewAtomTypes.length > 0 && <ElementLegend elements={previewAtomTypes} />}

          {/* 3D viewer with error overlay */}
          <div className="h-[400px] relative rounded border border-slate-700 overflow-hidden">
            {previewErrorMessage && (
              <div className="absolute top-2 left-2 right-2 z-10 rounded bg-red-500/15 border border-red-500/30 px-3 py-2 flex items-center gap-2 text-red-300 text-sm">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span>{previewErrorMessage}</span>
              </div>
            )}
            {!previewErrorMessage && preview?.xyz && (
              <SimpleViewer
                xyzData={preview.xyz}
                boxSize={preview.box_size}
                bonds={preview.bonds}
                showAxes
                zUp
                fitToFrame
                fitPadding={1.04}
                representation={representation}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default CrystalDetailPanel
