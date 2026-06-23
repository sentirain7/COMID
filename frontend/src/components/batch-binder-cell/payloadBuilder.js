import { getBinderComposition, precomputeTypingChargeCache } from '../../api/client'
import { defaultForm } from './config'

/**
 * Build the request payload for batch job binder cell submission.
 *
 * Pure function: takes form state and computed values, returns either
 * { payload: {...} } or { error: 'message' }.
 *
 * Args:
 *   form: current form state object
 *   ffType: selected force field type string
 *   additiveSummary: computed additive summary (concentrations, totalAdditiveWeight)
 *   selectedStages: stage selection object from useProtocolStages
 *   viscosityTemps: viscosity temperature array
 *   similarExistingAction: string action for similar experiments
 *   excludedExpIds: Set of excluded experiment IDs
 *   buildStageOverrides: function returning stage duration overrides
 *   buildStageRequests: function returning stage requests
 *   buildEquilibrationSettings: function returning equilibration payload
 *   eIntraMethod: selected E_intra method string
 *
 * Returns:
 *   { payload: {...} } on success, { error: string } on validation failure
 */
export function buildRequestPayload({
  form,
  ffType,
  additiveSummary,
  selectedStages,
  viscosityTemps,
  similarExistingAction,
  excludedExpIds,
  buildStageOverrides,
  buildStageRequests,
  buildEquilibrationSettings,
  interactionAnalysis = null,
  eIntraMethod,
}) {
  const binderTypes = form.binder_types
  if (binderTypes.length === 0) {
    return { error: 'Binder types must have at least one value.' }
  }

  const structureSizes = form.structure_sizes
  if (structureSizes.length === 0) {
    return { error: 'Structure sizes must have at least one value.' }
  }

  const agingStates = form.aging_states
  if (agingStates.length === 0) {
    return { error: 'Aging states must have at least one value.' }
  }

  const temperatures = form.temperatures_k
  if (!Array.isArray(temperatures) || temperatures.length === 0) {
    return { error: 'Temperatures must have at least one value.' }
  }

  const tempPriority = form.temperature_priority
  if (!Array.isArray(tempPriority)) {
    return { error: 'Temperature priority format is invalid.' }
  }

  const seed = Number(form.seed)
  if (!Number.isInteger(seed) || seed < 0) {
    return { error: 'Seed must be a non-negative integer.' }
  }

  // Keep 'none' in additive_types for backend to generate control group
  const additiveTypesForPayload = form.additive_types
  const realAdditiveTypes = form.additive_types.filter((t) => t !== 'none')
  const additiveConcentrations = additiveSummary.concentrations
  if (realAdditiveTypes.length > 0 && additiveSummary.totalAdditiveWeight <= 0) {
    return { error: 'Selected additives must have molecule count and molecular weight greater than 0.' }
  }

  const stageDurationOverrides = buildStageOverrides()
  const stageRequests = buildStageRequests()
  const propertyCalculations = selectedStages.viscosity_nemd
    ? {
        viscosity_enabled: true,
        viscosity_temperatures: viscosityTemps,
        tensile_enabled: false,
        tensile_temperatures: [],
      }
    : null

  // Equilibration settings: built from protocol stages (high_temp_nvt, high_pressure_npt)
  const equilibrationPayload = buildEquilibrationSettings()

  // Build interaction_analysis payload if enabled
  const interactionAnalysisPayload = interactionAnalysis?.enabled
    ? {
        enabled: true,
        mode: 'gpu_then_cpu',
        metrics: interactionAnalysis.metrics || ['e_inter_total'],
        auto_trigger_rerun: interactionAnalysis.auto_trigger_rerun ?? true,
      }
    : null

  return {
    payload: {
      binder_types: binderTypes,
      structure_sizes: structureSizes,
      temperatures_k: temperatures,
      aging_states: agingStates,
      tier: form.tier,
      ff_type: ffType,
      e_intra_method: eIntraMethod,
      seed,
      temperature_priority: tempPriority,
      additive_types: additiveTypesForPayload,
      additive_concentrations: additiveConcentrations,
      initial_density: form.initial_density,
      stage_requests: stageRequests,
      stage_durations: stageDurationOverrides.length > 0 ? stageDurationOverrides : null,
      property_calculations: propertyCalculations,
      equilibration_settings: equilibrationPayload,
      similar_existing_action: similarExistingAction,
      excluded_exp_ids: [...excludedExpIds],
      interaction_analysis: interactionAnalysisPayload,
    },
  }
}

/**
 * Build combination list for precompute cache from form state.
 *
 * Args:
 *   form: current form state object
 *
 * Returns:
 *   Array of { binderType, structureSize, agingState, tempCode } objects
 */
export function buildPrecomputeCombinations(form) {
  const binderTypes = form.binder_types.length > 0 ? form.binder_types : [defaultForm.binder_types[0]]
  const structureSizes = form.structure_sizes.length > 0 ? form.structure_sizes : [defaultForm.structure_sizes[0]]
  const agingStates = form.aging_states.length > 0 ? form.aging_states : [defaultForm.aging_states[0]]
  const temperatures = form.temperatures_k.length > 0 ? form.temperatures_k : [defaultForm.temperatures_k[0]]

  const combinations = []
  binderTypes.forEach((binderType) => {
    structureSizes.forEach((structureSize) => {
      agingStates.forEach((agingState) => {
        temperatures.forEach((temperature) => {
          combinations.push({
            binderType,
            structureSize,
            agingState,
            tempCode: String(Math.round(temperature)).padStart(4, '0'),
          })
        })
      })
    })
  })

  return combinations
}

/**
 * Resolve molecule counts across all batch combinations via composition API calls.
 *
 * Args:
 *   combinations: array from buildPrecomputeCombinations
 *
 * Returns:
 *   { moleculeCounts: Map<molId, count>, compositionFailures: number }
 */
export async function resolvePrecomputeMolecules(combinations) {
  const settled = await Promise.allSettled(
    combinations.map((item) =>
      getBinderComposition(item.binderType, item.structureSize, item.agingState, item.tempCode),
    ),
  )

  const moleculeCounts = new Map()
  let compositionFailures = 0
  settled.forEach((result) => {
    if (result.status !== 'fulfilled') {
      compositionFailures += 1
      return
    }
    const molecules = result.value?.molecules || []
    molecules.forEach((mol) => {
      const molId = mol?.mol_id
      const count = Math.max(0, Number(mol?.count || 0))
      if (!molId || count <= 0) return
      moleculeCounts.set(molId, (moleculeCounts.get(molId) || 0) + count)
    })
  })

  return { moleculeCounts, compositionFailures }
}

/**
 * Build additive specs for the precompute cache request.
 *
 * Args:
 *   form: current form state
 *   additiveCounts: { [additiveType]: count }
 *   additiveCatalog: { [mol_id]: catalogEntry }
 *   primaryStructureSize: the first structure size
 *
 * Returns:
 *   Array of { mol_id, count } or empty array
 */
export function buildAdditiveSpecs({ form, additiveCounts, additiveCatalog, primaryStructureSize }) {
  return form.additive_types
    .filter((t) => t !== 'none')
    .map((additiveType) => ({
      mol_id: additiveType,
      count: Math.max(
        0,
        Number(
          additiveCounts[additiveType] ??
            additiveCatalog[additiveType]?.default_counts?.[primaryStructureSize] ??
            0,
        ),
      ),
    }))
    .filter((item) => item.count > 0)
}

/**
 * Execute the precompute typing/charge cache API call.
 *
 * Args:
 *   moleculeCounts: Map<molId, count>
 *   additiveSpecs: array from buildAdditiveSpecs
 *   previewBasis: { binderType, structureSize, agingState }
 *   combinations: combination list (for fallback binder/size/aging)
 *   ffType: force field type string
 *
 * Returns:
 *   API response from precomputeTypingChargeCache
 */
export async function executePrecomputeCache({
  moleculeCounts,
  additiveSpecs,
  previewBasis,
  combinations,
  ffType,
}) {
  return precomputeTypingChargeCache({
    binder_type: previewBasis.binderType || combinations[0]?.binderType,
    structure_size: previewBasis.structureSize || combinations[0]?.structureSize,
    aging_state: previewBasis.agingState || combinations[0]?.agingState,
    ff_type: ffType,
    molecule_counts: Array.from(moleculeCounts.entries()).map(([mol_id, count]) => ({
      mol_id,
      count,
    })),
    additives: additiveSpecs.length > 0 ? additiveSpecs : null,
  })
}
