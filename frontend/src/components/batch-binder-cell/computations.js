import { getAdditiveDisplayName } from '../../lib/additiveLabel'
import { AGING_CODE, BINDER_CODE } from './config'

/**
 * Format a system key from binder type, aging state, and structure size.
 *
 * Args:
 *   binderType: binder type string (e.g. 'AAA1')
 *   agingState: aging state string (e.g. 'non_aging')
 *   structureSize: structure size string (e.g. 'X1')
 *
 * Returns:
 *   Formatted system key string (e.g. 'A1UX1')
 */
export function formatSystemKey(binderType, agingState, structureSize) {
  const binderCode = BINDER_CODE[binderType] || binderType
  const agingCode = AGING_CODE[agingState] || agingState
  return `${binderCode}${agingCode}${structureSize}`
}

/**
 * Compute additive summary for display in the batch binder cell UI.
 *
 * Args:
 *   additiveCatalog: { [mol_id]: catalogEntry }
 *   additiveCounts: { [additiveType]: number }
 *   binderWeightBySystem: { [systemKey]: { binderWeight, ... } }
 *   additiveTypes: array of additive type strings (may include 'none')
 *   previewBasis: { binderType, agingState, structureSize }
 *
 * Returns:
 *   { referenceSystemKey, referenceBinderWeight, rows, systemRows,
 *     totalAdditiveWeight, concentrations }
 */
export function computeAdditiveSummary({
  additiveCatalog,
  additiveCounts,
  binderWeightBySystem,
  additiveTypes,
  previewBasis,
}) {
  const referenceKey = `${previewBasis.binderType}|${previewBasis.agingState}|${previewBasis.structureSize}`
  const referenceSystem = binderWeightBySystem[referenceKey]
  const referenceBinderWeight = Number(referenceSystem?.binderWeight || 0)

  const rows = additiveTypes
    .filter((t) => t !== 'none')
    .map((additiveType) => {
      const item = additiveCatalog[additiveType] || {}
      const molecularWeight = Number(item.molecular_weight || 0)
      const moleculeCount = Math.max(0, Number(additiveCounts[additiveType] ?? 0))
      const weight = moleculeCount * molecularWeight
      return {
        additiveType,
        displayName: getAdditiveDisplayName(additiveType, additiveCatalog),
        molecularWeight,
        moleculeCount,
        weight,
      }
    })

  const totalAdditiveWeight = rows.reduce((sum, row) => sum + row.weight, 0)
  const denominator = referenceBinderWeight + totalAdditiveWeight
  const rowsWithRatio = rows.map((row) => ({
    ...row,
    ratioPct: denominator > 0 ? (row.weight / denominator) * 100 : 0,
  }))

  const systemRows = Object.values(binderWeightBySystem).map((system) => ({
    ...system,
    systemKey: formatSystemKey(system.binderType, system.agingState, system.structureSize),
    totalConcentrationPct:
      system.binderWeight + totalAdditiveWeight > 0
        ? (totalAdditiveWeight / (system.binderWeight + totalAdditiveWeight)) * 100
        : 0,
  }))

  return {
    referenceSystemKey: formatSystemKey(previewBasis.binderType, previewBasis.agingState, previewBasis.structureSize),
    referenceBinderWeight,
    rows: rowsWithRatio,
    systemRows,
    totalAdditiveWeight,
    concentrations: rowsWithRatio.map((row) => Number(row.ratioPct.toFixed(6))),
  }
}

/**
 * Compute composition cards from molecule counts and additives.
 *
 * Args:
 *   previewMoleculeCounts: array of { mol_id, sara_type, count, atom_count }
 *   additiveTypes: array of additive type strings (may include 'none')
 *   additiveCatalog: { [mol_id]: catalogEntry }
 *   additiveCounts: { [additiveType]: number }
 *
 * Returns:
 *   Array of card objects { key, molId, title, saraType?, subtitle?, count, atomCount, kind, index? }
 */
export function computeCompositionCards({
  previewMoleculeCounts,
  additiveTypes,
  additiveCatalog,
  additiveCounts,
}) {
  const binderCards = (previewMoleculeCounts || []).map((mol, index) => ({
    key: `mol:${mol.mol_id}`,
    molId: mol.mol_id,
    title: mol.mol_id,
    saraType: mol.sara_type,
    count: mol.count,
    atomCount: mol.atom_count || 50,
    kind: 'binder',
    index,
  }))

  const additiveCards = additiveTypes
    .filter((t) => t !== 'none')
    .map((additiveType) => {
      const item = additiveCatalog[additiveType] || {}
      const subtitle = item.name && item.name !== additiveType
        ? additiveType
        : (item.category || 'Additive')
      return {
        key: `add:${additiveType}`,
        molId: additiveType,
        title: item.name || additiveType,
        subtitle,
        count: Math.max(0, Number(additiveCounts[additiveType] ?? 0)),
        atomCount: item.atom_count || 50,
        kind: 'additive',
      }
    })

  return [...binderCards, ...additiveCards]
}

/**
 * Compute preview totals from composition cards.
 *
 * Args:
 *   compositionCards: array of card objects with count and atomCount
 *
 * Returns:
 *   { totalMolecules: number, estimatedAtoms: number }
 */
export function computePreviewTotals(compositionCards) {
  const totalMolecules = compositionCards.reduce((sum, card) => sum + Number(card.count || 0), 0)
  const estimatedAtoms = compositionCards.reduce(
    (sum, card) => sum + Number(card.count || 0) * (card.atomCount || 50),
    0,
  )
  return { totalMolecules, estimatedAtoms }
}
