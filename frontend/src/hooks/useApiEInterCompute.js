/**
 * E_inter Compute API Hooks
 *
 * Hooks for CPU rerun precision analysis recommendation and job management.
 */
import { useMemo } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

/**
 * Hook to fetch E_inter precision analysis recommendation.
 *
 * @param {Object} params - Recommendation parameters
 * @param {string} params.workflow - Workflow type
 * @param {string} [params.tier] - Run tier
 * @param {number} [params.layer_count] - Number of layers
 * @param {boolean} [params.has_additive] - Whether additives are included
 * @param {boolean} [params.has_water_ion] - Whether water/ion molecules are included
 * @param {number} [params.estimated_atoms] - Estimated atom count
 * @param {boolean} [enabled=true] - Whether to enable the query
 * @returns {Object} Query result with recommendation data
 */
export function useEInterRecommendation(params, enabled = true) {
  const paramsKey = useMemo(() => JSON.stringify(params || {}), [params])

  const query = useQuery({
    queryKey: ['e-inter-recommendation', paramsKey],
    enabled: Boolean(enabled && params?.workflow),
    queryFn: async () => {
      const { getEInterRecommendation } = await import('../api/client')
      return getEInterRecommendation(params)
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    cacheTime: 10 * 60 * 1000, // 10 minutes
  })

  return wrapQuery(query)
}

/**
 * Mutation hook to create a CPU rerun job.
 *
 * @returns {Object} Mutation object with mutate/mutateAsync functions
 */
export function useCreateCpuRerunJob() {
  return useMutation({
    mutationFn: async ({ expId, metrics }) => {
      const { createCpuRerunJob } = await import('../api/client')
      return createCpuRerunJob(expId, { metrics })
    },
  })
}

/**
 * Hook to fetch CPU rerun job status.
 *
 * @param {string} expId - Experiment ID
 * @param {boolean} [enabled=true] - Whether to enable the query
 * @returns {Object} Query result with job status
 */
export function useCpuRerunJobStatus(expId, enabled = true) {
  const query = useQuery({
    queryKey: ['cpu-rerun-job', expId],
    enabled: Boolean(enabled && expId),
    queryFn: async () => {
      const { getCpuRerunJobStatus } = await import('../api/client')
      return getCpuRerunJobStatus(expId)
    },
    refetchInterval: (query) => {
      const data = query.state.data
      // Poll while job is running
      if (data?.status === 'running' || data?.status === 'queued') {
        return 5000 // 5 seconds
      }
      return false
    },
  })

  return wrapQuery(query)
}
