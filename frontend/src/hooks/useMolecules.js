import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listMolecules } from '../api/client'

/**
 * Hook for fetching and managing molecule data.
 */
export function useMolecules({
  saraType,
  agingState,
  temperatureCode,
  limit = 500,
  // PR 2 (Method 1a SSOT, Codex Round 6): forward optional method tag so
  // the molecule list query can request a specific method's coverage view.
  // Cache key includes ``eIntraMethod`` so Method 1 / 1a results don't
  // collide in React Query cache.
  eIntraMethod,
} = {}) {
  const filters = useMemo(
    () => ({ saraType, agingState, temperatureCode, limit, eIntraMethod }),
    [saraType, agingState, temperatureCode, limit, eIntraMethod]
  )

  const filteredQuery = useQuery({
    queryKey: ['molecules', filters],
    queryFn: () => listMolecules(filters),
  })

  // Keep total category/aging counts independent from active filters.
  const totalsQuery = useQuery({
    queryKey: ['molecules', 'totals'],
    queryFn: () => listMolecules({ limit }),
  })

  const molecules = filteredQuery.data?.molecules || []
  const total = filteredQuery.data?.total || 0

  const totalCounts = useMemo(() => {
    const base = totalsQuery.data?.molecules || []
    const categories = {}
    const agingStates = {}

    base.forEach((mol) => {
      const cat = mol.category || 'unknown'
      categories[cat] = (categories[cat] || 0) + 1

      const aging = mol.aging_state || 'non_aging'
      agingStates[aging] = (agingStates[aging] || 0) + 1
    })

    return { categories, agingStates }
  }, [totalsQuery.data])

  return {
    molecules,
    loading: filteredQuery.isLoading,
    isFetching: filteredQuery.isFetching,
    error: filteredQuery.error?.message || null,
    total,
    totalCounts,
    refetch: filteredQuery.refetch,
  }
}

/**
 * Calculate counts by category from molecule list.
 */
export function getCategoryCounts(molecules) {
  return molecules.reduce((acc, mol) => {
    const cat = mol.category || 'unknown'
    acc[cat] = (acc[cat] || 0) + 1
    return acc
  }, {})
}

/**
 * Calculate counts by aging state from molecule list.
 */
export function getAgingCounts(molecules) {
  return molecules.reduce((acc, mol) => {
    const aging = mol.aging_state || 'non_aging'
    acc[aging] = (acc[aging] || 0) + 1
    return acc
  }, {})
}

export default useMolecules
