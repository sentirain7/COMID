import CompositionCards from '../CompositionCards'

function BatchJobBinderCellCompositionPanel({
  loadingComposition,
  previewTotals,
  compositionCards,
  onPreviewMolecule,
  previewBasis,
  setPreviewBasis,
  form,
  defaultForm,
}) {
  return (
    <div className="text-sm text-slate-300 md:col-span-2 flex flex-col">
      <div className="text-sm font-semibold mb-1 flex items-center gap-2">
        Composition
        {loadingComposition && (
          <div className="w-3 h-3 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
        )}
        <span className="text-xs text-slate-400 font-normal">
          {previewTotals.totalMolecules} mol / ~{(previewTotals.estimatedAtoms / 1000).toFixed(1)}k atoms
        </span>
      </div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1 flex flex-col min-h-0">
        <div className="flex-1 min-h-0 overflow-y-auto">
          <CompositionCards cards={compositionCards} onPreview={onPreviewMolecule} />
        </div>
        <div className="mt-2 pt-2 border-t border-slate-700 flex items-center gap-2 text-xs text-slate-400 flex-nowrap overflow-x-auto whitespace-nowrap">
          <span className="text-slate-500">Preview basis</span>
          <select
            value={previewBasis.binderType}
            onChange={(e) => setPreviewBasis((prev) => ({ ...prev, binderType: e.target.value }))}
            className="input py-1 text-xs bg-slate-700/60"
          >
            {(form.binder_types.length > 0 ? form.binder_types : [defaultForm.binder_types[0]]).map((binderType) => (
              <option key={binderType} value={binderType}>{binderType}</option>
            ))}
          </select>
          <select
            value={previewBasis.structureSize}
            onChange={(e) => setPreviewBasis((prev) => ({ ...prev, structureSize: e.target.value }))}
            className="input py-1 text-xs bg-slate-700/60"
          >
            {(form.structure_sizes.length > 0 ? form.structure_sizes : [defaultForm.structure_sizes[0]]).map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
          <select
            value={previewBasis.agingState}
            onChange={(e) => setPreviewBasis((prev) => ({ ...prev, agingState: e.target.value }))}
            className="input py-1 text-xs bg-slate-700/60"
          >
            {(form.aging_states.length > 0 ? form.aging_states : [defaultForm.aging_states[0]]).map((state) => (
              <option key={state} value={state}>{state}</option>
            ))}
          </select>
          <select
            value={previewBasis.temperature}
            onChange={(e) => setPreviewBasis((prev) => ({ ...prev, temperature: Number(e.target.value) }))}
            className="input py-1 text-xs bg-slate-700/60"
          >
            {(form.temperatures_k.length > 0 ? form.temperatures_k : [defaultForm.temperatures_k[0]]).map((temp) => (
              <option key={temp} value={temp}>{temp}K</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  )
}

export default BatchJobBinderCellCompositionPanel
