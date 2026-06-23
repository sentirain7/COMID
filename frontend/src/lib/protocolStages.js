import protocolStageCatalog from './protocolStageCatalog.json'

export const LAYER_CHAIN_KEYS = new Set(['layer', 'tensile_layer'])
export const EQUILIBRATION_STAGE_KEYS = new Set(['high_temp_nvt', 'high_pressure_npt'])
export const RUN_TIER_PRIORITY = protocolStageCatalog.run_tier_priority

const FALLBACK_PROTOCOL_STAGES = protocolStageCatalog.stages
const OPTIONAL_STAGE_KEYS_BY_CHAIN = protocolStageCatalog.chains.optional_stage_keys_by_chain
const BASE_STAGE_KEYS_BY_CHAIN = protocolStageCatalog.chains.base_stage_keys_by_chain

function clone(value) {
  if (typeof structuredClone === 'function') {
    return structuredClone(value)
  }
  return JSON.parse(JSON.stringify(value))
}

function normalizeStageDefinition(stageKey, definition) {
  const rawUiMetadata = definition.ui_metadata || {}
  const rawEquilibrationPayload = rawUiMetadata.equilibration_payload || {}
  return {
    stageKey,
    displayName: definition.display_name,
    compactDisplayName: definition.compact_display_name || definition.display_name,
    shortName: definition.short_name,
    color: definition.color,
    type: definition.type,
    optional: definition.optional,
    editableFields: definition.editable_fields || [],
    bounds: clone(definition.bounds || {}),
    uiMetadata: {
      ...clone(rawUiMetadata),
      defaultTemperatureK: rawUiMetadata.default_temperature_K,
      defaultPressureAtm: rawUiMetadata.default_pressure_atm,
      submitTier: rawUiMetadata.submit_tier,
      virtualSelector: rawUiMetadata.virtual_selector || false,
      selectorDescription: rawUiMetadata.selector_description || null,
      parameterFields: (rawUiMetadata.parameter_fields || []).map((field) => ({
        field: field.field,
        label: field.label,
        unit: field.unit,
        step: field.step ?? 1,
        parseAs: field.parse_as || field.parseAs || 'float',
      })),
      equilibrationPayload: rawUiMetadata.equilibration_payload
        ? {
          durationKey: rawEquilibrationPayload.duration_key,
          params: rawEquilibrationPayload.params || {},
        }
        : undefined,
    },
    orderIndex: definition.order_index ?? 0,
    durationPs: definition.default_duration_ps ?? null,
    durationSteps: definition.default_duration_steps ?? null,
    textClass: definition.text_class || null,
  }
}

export function getFallbackStageDefinition(stageKey) {
  const definition = FALLBACK_PROTOCOL_STAGES[stageKey]
  return definition ? normalizeStageDefinition(stageKey, definition) : null
}

export function getOptionalStageKeys(chainKey) {
  return [...(OPTIONAL_STAGE_KEYS_BY_CHAIN[chainKey] || [])]
}

export function getFallbackStageKeys(chainKey) {
  const base = BASE_STAGE_KEYS_BY_CHAIN[chainKey] || BASE_STAGE_KEYS_BY_CHAIN.screening
  return [...new Set([...base, ...getOptionalStageKeys(chainKey)])]
}

export function getStageSelectionDefault(stageKey, cfg, requiredStages = [], chainKey) {
  if (requiredStages.includes(stageKey)) return true
  if (EQUILIBRATION_STAGE_KEYS.has(stageKey) && !LAYER_CHAIN_KEYS.has(chainKey)) return true
  // Layer chain: base stages default ON even if optional
  if (LAYER_CHAIN_KEYS.has(chainKey)) {
    const baseKeys = BASE_STAGE_KEYS_BY_CHAIN[chainKey]
    if (baseKeys && baseKeys.includes(stageKey)) return true
  }
  return !cfg?.optional
}

export function getStageParameterFields(stageConfig, stageKey) {
  return [...(stageConfig[stageKey]?.uiMetadata?.parameterFields || [])]
}

export function isVirtualSelectorStage(stageConfig, stageKey) {
  return Boolean(stageConfig[stageKey]?.uiMetadata?.virtualSelector)
}

export function buildEquilibrationDefaults(stageConfig, stageDurations) {
  const result = {}
  for (const stageKey of EQUILIBRATION_STAGE_KEYS) {
    const cfg = stageConfig[stageKey] || {}
    const fallback = getFallbackStageDefinition(stageKey) || {}
    const uiMetadata = cfg.uiMetadata || fallback.uiMetadata || {}
    result[stageKey] = {
      temperature_K: uiMetadata.defaultTemperatureK ?? 500,
      duration_ps: stageDurations[stageKey]?.ps ?? fallback.durationPs ?? null,
    }
    if (getStageParameterFields(stageConfig, stageKey).some((field) => field.field === 'pressure_atm')) {
      result[stageKey].pressure_atm = uiMetadata.defaultPressureAtm ?? 100
    }
  }
  return result
}

export function resolveComputedRunTier(selectedStages, stageConfig, defaultChainKey) {
  if (defaultChainKey) return defaultChainKey

  let resolvedTier = 'screening'
  for (const [stageKey, enabled] of Object.entries(selectedStages)) {
    if (!enabled) continue
    const submitTier = stageConfig[stageKey]?.uiMetadata?.submitTier
    if (!submitTier) continue
    if ((RUN_TIER_PRIORITY[submitTier] ?? -1) > (RUN_TIER_PRIORITY[resolvedTier] ?? -1)) {
      resolvedTier = submitTier
    }
  }
  return resolvedTier
}

export function buildEquilibrationSettingsPayload({
  selectedStages,
  stageConfig,
  stageDurations,
  stageDefaults,
  equilibrationParams,
}) {
  const equilibrationEnabled = [...EQUILIBRATION_STAGE_KEYS].some((stageKey) => selectedStages[stageKey])
  if (!equilibrationEnabled) return null

  const defaultEqParams = buildEquilibrationDefaults(stageConfig, stageDefaults)
  const payload = { enabled: true }

  for (const stageKey of EQUILIBRATION_STAGE_KEYS) {
    const uiMetadata = stageConfig[stageKey]?.uiMetadata || {}
    const payloadConfig = uiMetadata.equilibrationPayload
    if (!payloadConfig) continue

    payload[payloadConfig.durationKey] =
      stageDurations[stageKey]?.ps ?? defaultEqParams[stageKey]?.duration_ps ?? null

    Object.entries(payloadConfig.params || {}).forEach(([paramField, payloadKey]) => {
      payload[payloadKey] =
        equilibrationParams[stageKey]?.[paramField]
        ?? defaultEqParams[stageKey]?.[paramField]
        ?? null
    })
  }

  return payload
}

// ─── Queue Panel Adapters ────────────────────────────────────────────────────
// Provides labels and visual styles for ExperimentQueuePanel, sourced from the
// protocol catalog SSOT rather than local hardcoded maps.

const QUEUE_LABEL_OVERRIDES = { minimize: 'Minimize' }

export function getQueueStageLabel(stage) {
  if (QUEUE_LABEL_OVERRIDES[stage]) return QUEUE_LABEL_OVERRIDES[stage]
  return getFallbackStageDefinition(stage)?.shortName || stage
}

export function getQueueStageVisual(stage) {
  const def = getFallbackStageDefinition(stage)
  return {
    bg: def?.color || '#3B82F6',
    text: def?.textClass || 'text-blue-200',
  }
}
