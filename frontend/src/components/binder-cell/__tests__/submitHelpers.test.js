import { describe, it, expect } from 'vitest'
import {
  validateSingleJobForm,
  buildSingleJobPayload,
} from '../submitHelpers'

// ─── validateSingleJobForm ───────────────────────────────────────────────────

describe('validateSingleJobForm', () => {
  it('returns null for valid input', () => {
    const result = validateSingleJobForm({
      moleculeCounts: [{ mol_id: 'mol-1', count: 3 }],
      totalMolecules: 3,
      seed: 42,
    })

    expect(result).toBeNull()
  })

  it('returns null when seed is empty string (auto-seed)', () => {
    const result = validateSingleJobForm({
      moleculeCounts: [{ mol_id: 'mol-1', count: 3 }],
      totalMolecules: 3,
      seed: '',
    })

    expect(result).toBeNull()
  })

  it('returns error when moleculeCounts is empty', () => {
    const result = validateSingleJobForm({
      moleculeCounts: [],
      totalMolecules: 0,
      seed: 42,
    })

    expect(result).toBe('No molecules in composition')
  })

  it('returns error when totalMolecules is zero', () => {
    const result = validateSingleJobForm({
      moleculeCounts: [{ mol_id: 'mol-1', count: 0 }],
      totalMolecules: 0,
      seed: 42,
    })

    expect(result).toBe('Total molecule count must be greater than 0')
  })

  it('returns error when seed is negative', () => {
    const result = validateSingleJobForm({
      moleculeCounts: [{ mol_id: 'mol-1', count: 3 }],
      totalMolecules: 3,
      seed: -5,
    })

    expect(result).toBe('Seed must be a non-negative integer')
  })

  it('returns error when seed is a non-integer string', () => {
    const result = validateSingleJobForm({
      moleculeCounts: [{ mol_id: 'mol-1', count: 3 }],
      totalMolecules: 3,
      seed: '3.14',
    })

    expect(result).toBe('Seed must be a non-negative integer')
  })
})

// ─── buildSingleJobPayload ───────────────────────────────────────────────────

describe('buildSingleJobPayload', () => {
  const baseArgs = {
    binderType: 'AAA1',
    structureSize: 'X1',
    agingState: 'non_aging',
    moleculeCounts: [{ mol_id: 'mol-1', count: 5 }],
    selectedAdditives: [],
    temperature: 293,
    boundaryMode: 'ppp',
    seed: 42,
    computedRunTier: 'screening',
    ffType: 'bulk_ff_gaff2',
    initialDensity: 0.5,
    selectedStages: { viscosity_nemd: false },
    viscosityTemps: [],
    buildStageOverrides: () => [],
    buildStageRequests: () => [],
    buildEquilibrationSettings: () => null,
    eIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
  }

  it('returns object with expected keys', () => {
    const payload = buildSingleJobPayload(baseArgs)

    expect(payload.binder_type).toBe('AAA1')
    expect(payload.structure_size).toBe('X1')
    expect(payload.aging_state).toBe('non_aging')
    expect(payload.temperature_K).toBe(293)
    expect(payload.e_intra_method).toBe('single_molecule_vacuum_adaptive_cutoff')
    expect(payload.study_type).toBe('bulk')
    expect(payload.seed).toBe(42)
    expect(payload.run_tier).toBe('screening')
    expect(payload.ff_type).toBe('bulk_ff_gaff2')
    expect(payload.initial_density).toBe(0.5)
    expect(payload.molecule_counts).toEqual([{ mol_id: 'mol-1', count: 5 }])
    expect(payload.additives).toBeNull()
    expect(payload.stage_durations).toBeNull()
    expect(payload.property_calculations).toBeNull()
    expect(payload.equilibration_settings).toBeNull()
  })

  it('sets study_type to layer_bulkff for ppf boundary mode', () => {
    const payload = buildSingleJobPayload({
      ...baseArgs,
      boundaryMode: 'ppf',
    })

    expect(payload.study_type).toBe('layer_bulkff')
  })

  it('sets seed to null when empty string', () => {
    const payload = buildSingleJobPayload({
      ...baseArgs,
      seed: '',
    })

    expect(payload.seed).toBeNull()
  })

  it('includes additive specs when present', () => {
    const payload = buildSingleJobPayload({
      ...baseArgs,
      selectedAdditives: [{ mol_id: 'SBS', count: 10 }],
    })

    expect(payload.additives).toEqual([{ mol_id: 'SBS', count: 10 }])
  })

  it('includes viscosity property_calculations when viscosity_nemd selected', () => {
    const payload = buildSingleJobPayload({
      ...baseArgs,
      selectedStages: { viscosity_nemd: true },
      viscosityTemps: [293],
    })

    expect(payload.property_calculations).toEqual({
      viscosity_enabled: true,
      viscosity_temperatures: [293],
      tensile_enabled: false,
      tensile_temperatures: [],
    })
  })
})
