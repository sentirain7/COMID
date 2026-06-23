/**
 * Pure function to compute total binder weight for a system.
 *
 * Used by both BinderCellSingleJobScreen (single system) and
 * BatchJobBinderCell (per-system weight map).
 *
 * Args:
 *   moleculeCounts: array of { mol_id, count, ... }
 *   agingState: aging state string (e.g. 'non_aging')
 *   moleculeWeightMap: { 'agingState:mol_id': number } lookup from useMoleculeWeights
 *
 * Returns:
 *   Total binder weight (sum of count * molecularWeight)
 */
export function computeBinderWeightForSystem(moleculeCounts, agingState, moleculeWeightMap) {
  if (!moleculeCounts || moleculeCounts.length === 0) return 0
  return moleculeCounts.reduce((sum, molecule) => {
    const baseId = molecule?.mol_id
    const molecularWeight =
      Number(moleculeWeightMap[`${agingState}:${baseId}`]) ||
      Number(moleculeWeightMap[`non_aging:${baseId}`]) ||
      0
    return sum + Number(molecule?.count || 0) * molecularWeight
  }, 0)
}
