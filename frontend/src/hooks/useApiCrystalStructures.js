import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

export function useCrystalStructures(filters = {}) {
  const filterKey = useMemo(() => JSON.stringify(filters || {}), [filters])
  const query = useQuery({
    queryKey: ['crystal-structures', filterKey],
    queryFn: async () => {
      const { listCrystalStructures } = await import('../api/client')
      return listCrystalStructures(filters || {})
    },
  })

  return wrapQuery(query)
}

export function useCrystalStructurePreview(crystalId, enabled = true) {
  const query = useQuery({
    queryKey: ['crystal-structure-preview', crystalId],
    enabled: Boolean(crystalId) && enabled,
    queryFn: async () => {
      const { getCrystalStructurePreview } = await import('../api/client')
      return getCrystalStructurePreview(crystalId)
    },
  })

  return wrapQuery(query)
}

export function useCreateCrystalStructure() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { createCrystalStructure } = await import('../api/client')
      return createCrystalStructure(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['crystal-structures'] })
    },
  })
}

export function useDeleteCrystalStructure() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (crystalId) => {
      const { deleteCrystalStructure } = await import('../api/client')
      return deleteCrystalStructure(crystalId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['crystal-structures'] })
    },
  })
}

export function useBatchGenerateCrystalSizes() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { batchGenerateCrystalSizes } = await import('../api/client')
      return batchGenerateCrystalSizes(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['crystal-structures'] })
    },
    throwOnError: false,
  })
}
