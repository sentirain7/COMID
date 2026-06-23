import { getTodaySeed } from '../../lib/seed'

const TODAY_SEED = getTodaySeed()

// Fallback defaults — used until /experiments/defaults API responds.
// SSOT is backend contracts.policies.temperature; these are static fallbacks only.
export const FALLBACK_TEMPERATURES_K = [213, 233, 253, 273, 293, 313, 333, 353, 373, 393, 413, 433]
export const FALLBACK_TEMPERATURE_PRIORITY = [293, 313]

export const defaultForm = {
  binder_types: ['AAA1'],
  structure_sizes: ['X1'],
  temperatures_k: FALLBACK_TEMPERATURES_K,
  aging_states: ['non_aging'],
  tier: 'screening',
  seed: TODAY_SEED,
  temperature_priority: FALLBACK_TEMPERATURE_PRIORITY,
  additive_types: ['none'],
  initial_density: 0.2,
  // High-temperature/high-pressure equilibration settings (enabled by default)
  // NOTE: These are fallback defaults. SSOT is contracts.policies.equilibration (backend).
  // Actual defaults are fetched from /settings/equilibration-defaults API endpoint.
  equilibration_settings: {
    enabled: true,
    high_temp_nvt_temperature_K: 500,
    high_temp_nvt_duration_ps: 100,
    high_pressure_npt_temperature_K: 500,
    high_pressure_npt_pressure_atm: 100,
    high_pressure_npt_duration_ps: 200,
  },
  // v00.95.02: similar experiment handling action
  similar_existing_action: 'unspecified',
}

// Similar experiment action options
export const SIMILAR_EXISTING_ACTION_OPTIONS = [
  { value: 'keep_priority', label: 'No, keep original priority', description: 'Submit with the original priority level' },
  { value: 'demote_priority', label: 'Yes, demote priority', description: 'Lower priority for jobs similar to existing experiments' },
]

export { AGING_ABBREV as AGING_CODE, BINDER_ABBREV as BINDER_CODE } from '../../lib/constants'

export const ADDITIVE_SUMMARY_GRID = 'grid-cols-[minmax(0,1fr)_52px_64px_72px_52px]'
