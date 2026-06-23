import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listMolecules } from '../api/client'

export function useMoleculeWeights(limit = 5000) {
  const query = useQuery({
    queryKey: ['molecule-weights', limit],
    queryFn: () => listMolecules({ limit }),
  })

  const weightMap = useMemo(() => {
    const molecules = query.data?.molecules || []
    const map = {}

    molecules.forEach((molecule) => {
      const baseId = molecule?.base_id
      const agingState = molecule?.aging_state || 'non_aging'
      const molecularWeight = Number(molecule?.molecular_weight || 0)
      if (!baseId || molecularWeight <= 0) return

      const key = `${agingState}:${baseId}`
      if (!map[key]) {
        map[key] = molecularWeight
      }
      if (!map[`non_aging:${baseId}`]) {
        map[`non_aging:${baseId}`] = molecularWeight
      }
    })

    return map
  }, [query.data])

  return {
    weightMap,
    loading: query.isLoading,
    error: query.error,
  }
}

export default useMoleculeWeights
