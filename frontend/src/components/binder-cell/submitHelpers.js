/**
 * Build the submission payload for a single binder cell experiment.
 *
 * Pure function: takes form state and protocol values, returns the payload object.
 *
 * Args:
 *   binderType: selected binder type string
 *   structureSize: selected structure size string
 *   agingState: selected aging state string
 *   moleculeCounts: array of { mol_id, count }
 *   selectedAdditives: array of { mol_id, count }
 *   temperature: temperature in K
 *   boundaryMode: 'ppp' or 'ppf'
 *   seed: seed value (string or number)
 *   computedRunTier: computed run tier string
 *   ffType: force field type string
 *   initialDensity: initial density value
 *   selectedStages: stage selection object from useProtocolStages
 *   viscosityTemps: viscosity temperature array
 *   buildStageOverrides: function returning stage duration overrides
 *   buildStageRequests: function returning stage requests
 *   buildEquilibrationSettings: function returning equilibration payload
 *   eIntraMethod: selected E_intra method string
 *
 * Returns:
 *   Complete submission payload object
 */
export function buildSingleJobPayload({
  binderType,
  structureSize,
  agingState,
  moleculeCounts,
  selectedAdditives,
  temperature,
  boundaryMode,
  seed,
  computedRunTier,
  ffType,
  initialDensity,
  selectedStages,
  viscosityTemps,
  buildStageOverrides,
  buildStageRequests,
  buildEquilibrationSettings,
  eIntraMethod,
  interactionAnalysis = null,
}) {
  const stageOverrides = buildStageOverrides()
  const stageRequests = buildStageRequests()
  const compositionPayload = {
    binder_type: binderType,
    structure_size: structureSize,
    aging_state: agingState,
    molecule_counts: moleculeCounts.map((m) => ({ mol_id: m.mol_id, count: m.count })),
    additives:
      selectedAdditives.length > 0
        ? selectedAdditives.map((a) => ({ mol_id: a.mol_id, count: a.count }))
        : null,
    temperature_K: temperature,
    e_intra_method: eIntraMethod,
    study_type: boundaryMode === 'ppf' ? 'layer_bulkff' : 'bulk',
    seed: seed === '' ? null : Number(seed),
  }

  return {
    ...compositionPayload,
    run_tier: computedRunTier,
    ff_type: ffType,
    initial_density: initialDensity,
    stage_requests: stageRequests,
    stage_durations: stageOverrides.length > 0 ? stageOverrides : null,
    property_calculations: selectedStages.viscosity_nemd
      ? {
          viscosity_enabled: true,
          viscosity_temperatures: viscosityTemps,
          tensile_enabled: false,
          tensile_temperatures: [],
        }
      : null,
    equilibration_settings: buildEquilibrationSettings(),
    interaction_analysis: interactionAnalysis,
  }
}

/**
 * Validate the single job form before submission.
 *
 * Args:
 *   moleculeCounts: array of molecule count objects
 *   totalMolecules: total molecule count
 *   seed: seed value (string or number)
 *
 * Returns:
 *   Error message string, or null if valid
 */
export function validateSingleJobForm({ moleculeCounts, totalMolecules, seed }) {
  if (moleculeCounts.length === 0) {
    return 'No molecules in composition'
  }
  if (totalMolecules === 0) {
    return 'Total molecule count must be greater than 0'
  }
  if (seed !== '' && (!Number.isInteger(Number(seed)) || Number(seed) < 0)) {
    return 'Seed must be a non-negative integer'
  }
  return null
}
