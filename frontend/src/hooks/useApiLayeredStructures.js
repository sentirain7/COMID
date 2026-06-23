import { useMemo } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

export function useLayeredExperiments(filters = {}) {
  const filterKey = useMemo(() => JSON.stringify(filters || {}), [filters])
  const query = useQuery({
    queryKey: ['layered-experiments', filterKey],
    queryFn: async () => {
      const { listLayeredExperiments } = await import('../api/client')
      return listLayeredExperiments(filters || {})
    },
  })
  return wrapQuery(query)
}

export function useStressStrainCurve(expId) {
  const query = useQuery({
    queryKey: ['stress-strain', expId],
    enabled: Boolean(expId),
    queryFn: async () => {
      const { getStressStrainCurve } = await import('../api/client')
      return getStressStrainCurve(expId)
    },
  })
  return wrapQuery(query)
}

export function useLayerSources(sourceType, limit = 100, visibility = 'library') {
  const key = useMemo(
    () => ['layered-sources', sourceType, limit, visibility],
    [sourceType, limit, visibility]
  )
  const query = useQuery({
    queryKey: key,
    enabled: Boolean(sourceType),
    queryFn: async () => {
      const { listLayerSources } = await import('../api/client')
      return listLayerSources(sourceType, { limit, visibility })
    },
  })
  return wrapQuery(query)
}

export function useLayeredStructurePreview() {
  return useMutation({
    mutationFn: async (payload) => {
      const { previewLayeredStructure } = await import('../api/client')
      return previewLayeredStructure(payload)
    },
  })
}

export function useLayeredStructureSubmit() {
  return useMutation({
    mutationFn: async (payload) => {
      const { submitLayeredStructure } = await import('../api/client')
      return submitLayeredStructure(payload)
    },
  })
}

export function useLayeredAnalysis3D(filters = {}) {
  const filterKey = useMemo(() => JSON.stringify(filters), [filters])
  const query = useQuery({
    queryKey: ['layered-analysis-3d', filterKey],
    queryFn: async () => {
      const { getLayeredAnalysis3D } = await import('../api/client')
      return getLayeredAnalysis3D(filters)
    },
  })
  return wrapQuery(query)
}
