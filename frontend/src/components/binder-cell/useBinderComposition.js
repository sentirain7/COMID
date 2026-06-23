import { useState, useEffect, useCallback } from 'react'
import { getBinderComposition } from '../../api/client'

/**
 * Shared hook for loading binder composition from the API.
 *
 * Handles fetching molecule counts, total molecules, estimated atoms,
 * and SARA fractions for a given binder type / structure size / aging state.
 *
 * Args:
 *   binderType: selected binder type string (e.g. 'AAA1')
 *   structureSize: selected structure size string (e.g. 'X1')
 *   agingState: selected aging state string (e.g. 'non_aging')
 *   tempCode: optional temperature code string (e.g. '0293')
 *   enabled: whether to fetch (set false to skip, e.g. in custom mode)
 *
 * Returns:
 *   { moleculeCounts, totalMolecules, estimatedAtoms, saraFractions,
 *     loading, error, refetch, setMoleculeCounts, setTotalMolecules,
 *     setEstimatedAtoms, setSaraFractions }
 */
export default function useBinderComposition({
  binderType,
  structureSize,
  agingState,
  tempCode,
  enabled = true,
}) {
  const [moleculeCounts, setMoleculeCounts] = useState([])
  const [totalMolecules, setTotalMolecules] = useState(0)
  const [estimatedAtoms, setEstimatedAtoms] = useState(0)
  const [saraFractions, setSaraFractions] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const loadComposition = useCallback(async () => {
    if (!enabled) return

    setLoading(true)
    setError(null)
    try {
      const response = await getBinderComposition(binderType, structureSize, agingState, tempCode)
      setMoleculeCounts(response.molecules || [])
      setTotalMolecules(response.total_molecules || 0)
      setEstimatedAtoms(response.estimated_atoms || 0)
      setSaraFractions(response.sara_fractions || {})
    } catch (err) {
      console.error('Failed to load composition:', err)
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [binderType, structureSize, agingState, tempCode, enabled])

  useEffect(() => {
    loadComposition()
  }, [loadComposition])

  return {
    moleculeCounts,
    totalMolecules,
    estimatedAtoms,
    saraFractions,
    loading,
    error,
    refetch: loadComposition,
    setMoleculeCounts,
    setTotalMolecules,
    setEstimatedAtoms,
    setSaraFractions,
  }
}
