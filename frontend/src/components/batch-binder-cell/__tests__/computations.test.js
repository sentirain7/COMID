import { describe, it, expect, vi } from 'vitest'
import {
  formatSystemKey,
  computeAdditiveSummary,
  computeCompositionCards,
  computePreviewTotals,
} from '../computations'

// Mock the additiveLabel module so we don't depend on its internals
vi.mock('../../../lib/additiveLabel', () => ({
  getAdditiveDisplayName: (molId) => molId || '',
}))

// Mock the config module to provide known BINDER_CODE / AGING_CODE values
vi.mock('../config', () => ({
  BINDER_CODE: { AAA1: 'A1', AAK1: 'K1', AAM1: 'M1' },
  AGING_CODE: { non_aging: 'NA', short_aging: 'SA', long_aging: 'LA' },
}))

// ─── formatSystemKey ─────────────────────────────────────────────────────────

describe('formatSystemKey', () => {
  it('formats known binder/aging/size correctly', () => {
    expect(formatSystemKey('AAA1', 'non_aging', 'X1')).toBe('A1NAX1')
  })

  it('formats different binder and aging combinations', () => {
    expect(formatSystemKey('AAK1', 'short_aging', 'X2')).toBe('K1SAX2')
    expect(formatSystemKey('AAM1', 'long_aging', 'X3')).toBe('M1LAX3')
  })

  it('falls back to raw values for unknown codes', () => {
    expect(formatSystemKey('CUSTOM', 'unknown_aging', 'X1')).toBe('CUSTOMunknown_agingX1')
  })
})

// ─── computeAdditiveSummary ──────────────────────────────────────────────────

describe('computeAdditiveSummary', () => {
  it('returns correct structure with empty inputs', () => {
    const result = computeAdditiveSummary({
      additiveCatalog: {},
      additiveCounts: {},
      binderWeightBySystem: {},
      additiveTypes: ['none'],
      previewBasis: { binderType: 'AAA1', agingState: 'non_aging', structureSize: 'X1' },
    })

    expect(result).toEqual({
      referenceSystemKey: 'A1NAX1',
      referenceBinderWeight: 0,
      rows: [],
      systemRows: [],
      totalAdditiveWeight: 0,
      concentrations: [],
    })
  })

  it('calculates weight and ratio when additives are present', () => {
    const result = computeAdditiveSummary({
      additiveCatalog: {
        SBS: { molecular_weight: 100 },
      },
      additiveCounts: { SBS: 5 },
      binderWeightBySystem: {
        'AAA1|non_aging|X1': {
          binderType: 'AAA1',
          agingState: 'non_aging',
          structureSize: 'X1',
          binderWeight: 500,
        },
      },
      additiveTypes: ['none', 'SBS'],
      previewBasis: { binderType: 'AAA1', agingState: 'non_aging', structureSize: 'X1' },
    })

    expect(result.referenceBinderWeight).toBe(500)
    expect(result.totalAdditiveWeight).toBe(500) // 5 * 100
    expect(result.rows).toHaveLength(1)
    expect(result.rows[0].weight).toBe(500)
    // 500 / (500 + 500) * 100 = 50%
    expect(result.rows[0].ratioPct).toBeCloseTo(50)
    expect(result.concentrations).toHaveLength(1)
    expect(result.concentrations[0]).toBeCloseTo(50)
  })

  it('generates systemRows with totalConcentrationPct', () => {
    const result = computeAdditiveSummary({
      additiveCatalog: { SBS: { molecular_weight: 200 } },
      additiveCounts: { SBS: 1 },
      binderWeightBySystem: {
        'AAA1|non_aging|X1': {
          binderType: 'AAA1',
          agingState: 'non_aging',
          structureSize: 'X1',
          binderWeight: 800,
        },
      },
      additiveTypes: ['SBS'],
      previewBasis: { binderType: 'AAA1', agingState: 'non_aging', structureSize: 'X1' },
    })

    expect(result.systemRows).toHaveLength(1)
    // 200 / (800 + 200) * 100 = 20%
    expect(result.systemRows[0].totalConcentrationPct).toBeCloseTo(20)
    expect(result.systemRows[0].systemKey).toBe('A1NAX1')
  })
})

// ─── computeCompositionCards ─────────────────────────────────────────────────

describe('computeCompositionCards', () => {
  it('returns array of card objects from binder molecules', () => {
    const cards = computeCompositionCards({
      previewMoleculeCounts: [
        { mol_id: 'mol-1', sara_type: 'asphaltene', count: 3, atom_count: 120 },
        { mol_id: 'mol-2', sara_type: 'resin', count: 5, atom_count: 80 },
      ],
      additiveTypes: ['none'],
      additiveCatalog: {},
      additiveCounts: {},
    })

    expect(cards).toHaveLength(2)
    expect(cards[0]).toMatchObject({
      key: 'mol:mol-1',
      molId: 'mol-1',
      title: 'mol-1',
      saraType: 'asphaltene',
      count: 3,
      atomCount: 120,
      kind: 'binder',
      index: 0,
    })
    expect(cards[1].kind).toBe('binder')
    expect(cards[1].index).toBe(1)
  })

  it('appends additive cards when additives are present', () => {
    const cards = computeCompositionCards({
      previewMoleculeCounts: [],
      additiveTypes: ['none', 'SBS'],
      additiveCatalog: { SBS: { name: 'SBS Polymer', category: 'Polymer' } },
      additiveCounts: { SBS: 10 },
    })

    expect(cards).toHaveLength(1)
    expect(cards[0]).toMatchObject({
      key: 'add:SBS',
      molId: 'SBS',
      title: 'SBS Polymer',
      count: 10,
      kind: 'additive',
    })
  })

  it('handles null previewMoleculeCounts gracefully', () => {
    const cards = computeCompositionCards({
      previewMoleculeCounts: null,
      additiveTypes: ['none'],
      additiveCatalog: {},
      additiveCounts: {},
    })

    expect(cards).toEqual([])
  })
})

// ─── computePreviewTotals ────────────────────────────────────────────────────

describe('computePreviewTotals', () => {
  it('sums molecules and atoms', () => {
    const cards = [
      { count: 3, atomCount: 100 },
      { count: 5, atomCount: 50 },
    ]
    const result = computePreviewTotals(cards)

    expect(result.totalMolecules).toBe(8)
    expect(result.estimatedAtoms).toBe(3 * 100 + 5 * 50) // 550
  })

  it('returns zeros for empty input', () => {
    const result = computePreviewTotals([])
    expect(result.totalMolecules).toBe(0)
    expect(result.estimatedAtoms).toBe(0)
  })

  it('defaults atomCount to 50 when missing', () => {
    const cards = [{ count: 2 }]
    const result = computePreviewTotals(cards)

    expect(result.totalMolecules).toBe(2)
    expect(result.estimatedAtoms).toBe(2 * 50) // 100
  })
})
