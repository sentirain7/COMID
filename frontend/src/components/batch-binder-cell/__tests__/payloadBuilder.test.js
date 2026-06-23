import { describe, it, expect, vi } from 'vitest'
import {
  buildRequestPayload,
  buildAdditiveSpecs,
  buildPrecomputeCombinations,
} from '../payloadBuilder'

// Mock external modules that payloadBuilder imports
vi.mock('../../../api/client', () => ({
  getBinderComposition: vi.fn(),
  precomputeTypingChargeCache: vi.fn(),
}))

vi.mock('../config', () => ({
  defaultForm: {
    binder_types: ['AAA1'],
    structure_sizes: ['X1'],
    aging_states: ['non_aging'],
    temperatures_k: [293],
  },
}))

// ─── buildRequestPayload ─────────────────────────────────────────────────────

describe('buildRequestPayload', () => {
  const validForm = {
    binder_types: ['AAA1'],
    structure_sizes: ['X1'],
    aging_states: ['non_aging'],
    temperatures_k: [293, 313],
    temperature_priority: [293],
    seed: 42,
    additive_types: ['none'],
    tier: 'screening',
    initial_density: 0.5,
  }

  const stubs = {
    ffType: 'bulk_ff_gaff2',
    additiveSummary: { concentrations: [], totalAdditiveWeight: 0 },
    selectedStages: { viscosity_nemd: false },
    viscosityTemps: [],
    similarExistingAction: 'keep_priority',
    excludedExpIds: new Set(),
    buildStageOverrides: () => [],
    buildStageRequests: () => [],
    buildEquilibrationSettings: () => null,
    eIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
  }

  it('returns error when binder_types is empty', () => {
    const result = buildRequestPayload({
      ...stubs,
      form: { ...validForm, binder_types: [] },
    })

    expect(result.error).toBe('Binder types must have at least one value.')
    expect(result.payload).toBeUndefined()
  })

  it('returns error when structure_sizes is empty', () => {
    const result = buildRequestPayload({
      ...stubs,
      form: { ...validForm, structure_sizes: [] },
    })

    expect(result.error).toBe('Structure sizes must have at least one value.')
  })

  it('returns error when aging_states is empty', () => {
    const result = buildRequestPayload({
      ...stubs,
      form: { ...validForm, aging_states: [] },
    })

    expect(result.error).toBe('Aging states must have at least one value.')
  })

  it('returns error when temperatures_k is empty', () => {
    const result = buildRequestPayload({
      ...stubs,
      form: { ...validForm, temperatures_k: [] },
    })

    expect(result.error).toBe('Temperatures must have at least one value.')
  })

  it('returns error when seed is negative', () => {
    const result = buildRequestPayload({
      ...stubs,
      form: { ...validForm, seed: -1 },
    })

    expect(result.error).toBe('Seed must be a non-negative integer.')
  })

  it('returns valid payload structure for valid input', () => {
    const result = buildRequestPayload({
      ...stubs,
      form: validForm,
    })

    expect(result.error).toBeUndefined()
    expect(result.payload).toBeDefined()
    expect(result.payload.binder_types).toEqual(['AAA1'])
    expect(result.payload.structure_sizes).toEqual(['X1'])
    expect(result.payload.temperatures_k).toEqual([293, 313])
    expect(result.payload.aging_states).toEqual(['non_aging'])
    expect(result.payload.tier).toBe('screening')
    expect(result.payload.ff_type).toBe('bulk_ff_gaff2')
    expect(result.payload.e_intra_method).toBe('single_molecule_vacuum_adaptive_cutoff')
    expect(result.payload.seed).toBe(42)
    expect(result.payload.additive_types).toEqual(['none'])
    expect(result.payload.initial_density).toBe(0.5)
    expect(result.payload.stage_durations).toBeNull()
    expect(result.payload.property_calculations).toBeNull()
  })

  it('includes viscosity property_calculations when viscosity_nemd is selected', () => {
    const result = buildRequestPayload({
      ...stubs,
      form: validForm,
      selectedStages: { viscosity_nemd: true },
      viscosityTemps: [293, 313],
    })

    expect(result.payload.property_calculations).toEqual({
      viscosity_enabled: true,
      viscosity_temperatures: [293, 313],
      tensile_enabled: false,
      tensile_temperatures: [],
    })
  })
})

// ─── buildAdditiveSpecs ──────────────────────────────────────────────────────

describe('buildAdditiveSpecs', () => {
  it('builds correct spec array from catalog and counts', () => {
    const specs = buildAdditiveSpecs({
      form: { additive_types: ['none', 'SBS', 'PPA'] },
      additiveCounts: { SBS: 5, PPA: 3 },
      additiveCatalog: {},
      primaryStructureSize: 'X1',
    })

    expect(specs).toEqual([
      { mol_id: 'SBS', count: 5 },
      { mol_id: 'PPA', count: 3 },
    ])
  })

  it('filters out none and zero-count additives', () => {
    const specs = buildAdditiveSpecs({
      form: { additive_types: ['none', 'SBS', 'PPA'] },
      additiveCounts: { SBS: 0, PPA: 2 },
      additiveCatalog: {},
      primaryStructureSize: 'X1',
    })

    expect(specs).toEqual([{ mol_id: 'PPA', count: 2 }])
  })

  it('uses catalog default_counts as fallback', () => {
    const specs = buildAdditiveSpecs({
      form: { additive_types: ['SBS'] },
      additiveCounts: {},
      additiveCatalog: { SBS: { default_counts: { X1: 4 } } },
      primaryStructureSize: 'X1',
    })

    expect(specs).toEqual([{ mol_id: 'SBS', count: 4 }])
  })

  it('returns empty array when only none is selected', () => {
    const specs = buildAdditiveSpecs({
      form: { additive_types: ['none'] },
      additiveCounts: {},
      additiveCatalog: {},
      primaryStructureSize: 'X1',
    })

    expect(specs).toEqual([])
  })
})

// ─── buildPrecomputeCombinations ─────────────────────────────────────────────

describe('buildPrecomputeCombinations', () => {
  it('generates cartesian product of binder/size/aging/temp', () => {
    const combos = buildPrecomputeCombinations({
      binder_types: ['AAA1', 'AAK1'],
      structure_sizes: ['X1'],
      aging_states: ['non_aging'],
      temperatures_k: [293, 313],
    })

    expect(combos).toHaveLength(4) // 2 binder * 1 size * 1 aging * 2 temp
    expect(combos[0]).toEqual({
      binderType: 'AAA1',
      structureSize: 'X1',
      agingState: 'non_aging',
      tempCode: '0293',
    })
    expect(combos[1]).toEqual({
      binderType: 'AAA1',
      structureSize: 'X1',
      agingState: 'non_aging',
      tempCode: '0313',
    })
    expect(combos[2].binderType).toBe('AAK1')
    expect(combos[3].binderType).toBe('AAK1')
  })

  it('falls back to defaultForm when arrays are empty', () => {
    const combos = buildPrecomputeCombinations({
      binder_types: [],
      structure_sizes: [],
      aging_states: [],
      temperatures_k: [],
    })

    // Falls back to defaultForm values: 1 binder * 1 size * 1 aging * 1 temp = 1
    expect(combos).toHaveLength(1)
    expect(combos[0]).toEqual({
      binderType: 'AAA1',
      structureSize: 'X1',
      agingState: 'non_aging',
      tempCode: '0293',
    })
  })

  it('pads tempCode to 4 digits', () => {
    const combos = buildPrecomputeCombinations({
      binder_types: ['AAA1'],
      structure_sizes: ['X1'],
      aging_states: ['non_aging'],
      temperatures_k: [77],
    })

    expect(combos[0].tempCode).toBe('0077')
  })
})
