import { PrecisionAnalysisPanel } from '../shared'

function BatchJobBinderCellSubmissionPanel({
  form,
  totalJobCount,
  additiveComboCount,
  computedRunTier,
  selectedStageNames,
  ffType,
  selectedStages,
  viscosityTemps,
  requestPayload,
  setValidationError,
  validateMutation,
  createMutation,
  onSubmitBatchJob,
  eInterRecommendation,
  onInteractionAnalysisChange,
  effectiveEIntraMethodLabel,
}) {
  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="text-sm text-slate-300">
          <div className="text-sm font-semibold mb-1">Scenario Conditions</div>
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 space-y-1.5 text-xs text-slate-400">
            <div>
              Total jobs: <span className="text-white">{totalJobCount}</span>{' '}
              <span className="text-slate-500">
                (binder {form.binder_types.length} × size {form.structure_sizes.length} × aging {form.aging_states.length} × temp {form.temperatures_k.length} × additive {additiveComboCount})
              </span>
            </div>
            <div>Tier (auto): <span className="text-white">{computedRunTier}</span></div>
            <div>Stages: <span className="text-white">{selectedStageNames.length > 0 ? selectedStageNames.join(', ') : 'none'}</span></div>
            <div>Temperatures: <span className="text-white">{form.temperatures_k.length > 0 ? form.temperatures_k.join(', ') : 'none'}</span></div>
            <div>Priority temps: <span className="text-white">{form.temperature_priority.length > 0 ? form.temperature_priority.join(', ') : 'none'}</span></div>
            <div>Force field: <span className="text-white">{ffType === 'reaxff' ? 'ReaxFF' : 'GAFF2'}</span></div>
            <div>E_intra method: <span className="text-white">{effectiveEIntraMethodLabel}</span></div>
            {selectedStages.viscosity_nemd && (
              <div>Viscosity temps: <span className="text-white">{viscosityTemps.join(', ')}</span></div>
            )}
          </div>
        </div>

        {eInterRecommendation && (
          <div className="text-sm text-slate-300">
            <div className="text-sm font-semibold mb-1">Precision Analysis Options</div>
            <PrecisionAnalysisPanel
              recommendation={eInterRecommendation}
              onChange={onInteractionAnalysisChange}
              compact
            />
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2">
        <button
          className="btn btn-secondary text-sm"
          onClick={() => {
            if (!requestPayload.payload) {
              setValidationError(requestPayload.error || 'Invalid batch job request.')
              return
            }
            setValidationError('')
            validateMutation.mutate(requestPayload.payload)
          }}
          disabled={validateMutation.isPending}
        >
          {validateMutation.isPending ? 'Building...' : 'Build Scenario'}
        </button>
        <button
          className="btn btn-primary text-sm"
          onClick={onSubmitBatchJob}
          disabled={createMutation.isPending}
        >
          {createMutation.isPending ? 'Submitting...' : 'Submit Batch Job'}
        </button>
      </div>
    </>
  )
}

export default BatchJobBinderCellSubmissionPanel
