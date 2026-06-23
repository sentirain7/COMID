import { Loader2 } from 'lucide-react'
import { SimpleViewer } from '../MoleculeViewer'

function LayerPreviewPanel({ previewData, previewMutation }) {
  return (
    <div className="md:col-span-2 flex flex-col min-h-0">
      <div className="font-medium text-sm text-slate-200 mb-2 flex items-center justify-between">
        <span>Layer Preview</span>
        {previewMutation.isPending && <Loader2 className="w-4 h-4 animate-spin text-blue-300" />}
      </div>
      {previewData ? (
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-300 mb-1">
            <span>Atoms: <span className="text-slate-100">{Number(previewData.n_atoms || 0).toLocaleString()}</span></span>
            <span>Bonds: <span className="text-slate-100">{Number(previewData.n_bonds || 0).toLocaleString()}</span></span>
            <span>
              Box: {Number(previewData.box_size?.[0] || 0).toFixed(1)} x {Number(previewData.box_size?.[1] || 0).toFixed(1)} x{' '}
              {Number(previewData.box_size?.[2] || 0).toFixed(1)} Å
            </span>
          </div>
          <div className="flex-1 min-h-[360px] rounded border border-slate-700 overflow-hidden">
            <SimpleViewer
              xyzData={previewData.xyz}
              boxSize={previewData.box_size}
              bonds={previewData.bonds}
              showAxes
              zUp
              fitToFrame
              fitPadding={1.05}
            />
          </div>
        </div>
      ) : (
        <div className="text-xs text-slate-400 flex-1 min-h-[360px] flex items-center justify-center border border-slate-700 rounded">
          Preview not generated yet.
        </div>
      )}
    </div>
  )
}

export default LayerPreviewPanel
