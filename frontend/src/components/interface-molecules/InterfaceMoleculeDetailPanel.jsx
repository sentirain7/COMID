import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import { SimpleViewer } from '../MoleculeViewer'
import { ElementLegend } from '../shared'
import { INTERFACE_MOLECULE_INFO } from './config'

function InterfaceMoleculeDetailPanel({
  selectedCellId,
  selectedCell,
  preview,
  previewLoading,
  previewError,
  previewElements,
  representation,
  setRepresentation,
  refreshPreview,
}) {
  const molInfo = INTERFACE_MOLECULE_INFO[selectedCell?.mol_id] || {}

  return (
    <div className="card p-4 space-y-3 sticky top-0 self-start">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Cell Preview</h2>
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
          {selectedCellId && (
            <button
              type="button"
              className="p-2 rounded bg-slate-700/70 text-slate-200 hover:bg-slate-700"
              onClick={() => refreshPreview()}
              title="Refresh preview"
            >
              {previewLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>

      {/* No selection */}
      {!selectedCellId && (
        <div className="text-sm text-slate-400 py-6 text-center">
          Select a cell from the table or batch result.
        </div>
      )}

      {selectedCellId && (
        <div className="space-y-3">
      {/* Info badges (Crystal pattern: above viewer) */}
      {selectedCell && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
          <span className="px-2 py-1 rounded bg-slate-700/70 font-medium">
            {molInfo.formula || selectedCell.mol_id}
          </span>
          {selectedCell.atom_count > 0 && (
            <span>{selectedCell.atom_count.toLocaleString()} atoms</span>
          )}
          {selectedCell.molecule_count > 0 && (
            <span>{selectedCell.molecule_count} molecules</span>
          )}
          {(selectedCell.actual_density || selectedCell.target_density) && (
            <span>{(selectedCell.actual_density || selectedCell.target_density).toFixed(3)} g/cm3</span>
          )}
        </div>
      )}

      {/* Cell dimensions */}
      {selectedCell && selectedCell.lx_angstrom != null && (
        <div className="text-xs text-slate-300 grid grid-cols-2 gap-x-3 gap-y-0.5">
          <span>lx: {selectedCell.lx_angstrom.toFixed(2)} A</span>
          <span>ly: {selectedCell.ly_angstrom.toFixed(2)} A</span>
          <span>lz: {selectedCell.lz_angstrom.toFixed(2)} A</span>
          <span>
            V: {(
              (selectedCell.lx_angstrom || 0) *
              (selectedCell.ly_angstrom || 0) *
              (selectedCell.lz_angstrom || 0)
            ).toFixed(1)} A^3
          </span>
        </div>
      )}

      {/* Cell metadata */}
      {selectedCell && (
        <div className="text-xs text-slate-400 space-y-0.5">
          {selectedCell.boundary_mode && <div>Boundary: {selectedCell.boundary_mode}</div>}
          {selectedCell.created_at && (
            <div>Created: {new Date(selectedCell.created_at).toLocaleDateString()}</div>
          )}
        </div>
      )}

      {/* Element legend */}
      {previewElements?.length > 0 && <ElementLegend elements={previewElements} />}

      {/* 3D viewer with error overlay */}
      <div className="h-[400px] relative rounded border border-slate-700 overflow-hidden">
        {previewError && (
          <div className="absolute top-2 left-2 right-2 z-10 rounded bg-red-500/15 border border-red-500/30 px-3 py-2 flex items-center gap-2 text-red-300 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{previewError}</span>
          </div>
        )}
        {!previewError && preview?.xyz && (
          <SimpleViewer
            xyzData={preview.xyz}
            boxSize={preview.box_size}
            bonds={preview.bonds}
            showAxes
            zUp
            showBox
            fitToFrame
            fitPadding={1.04}
            representation={representation}
          />
        )}
        {previewLoading && !preview?.xyz && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
          </div>
        )}
        {!previewLoading && !previewError && !preview?.xyz && (
          <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-xs">
            Loading preview...
          </div>
        )}
      </div>
        </div>
      )}
    </div>
  )
}

export default InterfaceMoleculeDetailPanel
