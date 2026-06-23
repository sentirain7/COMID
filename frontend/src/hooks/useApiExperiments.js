import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

const normalizeMetrics = (raw) => {
  if (!raw || !Array.isArray(raw.metrics)) {
    return null
  }

  const mapped = {}
  raw.metrics.forEach((m) => {
    if (m?.metric_name != null) {
      mapped[m.metric_name] = m.value
    }
  })
  return mapped
}

/**
 * Hook for experiments list with polling.
 */
export function useExperiments(filters = {}, interval = 5000, { enabled = true } = {}) {
  const filterKey = useMemo(() => JSON.stringify(filters), [filters])

  const query = useQuery({
    queryKey: ['experiments', filterKey],
    queryFn: async () => {
      const { listExperiments } = await import('../api/client')
      return listExperiments(filters)
    },
    enabled,
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for experiment details.
 */
export function useExperimentDetail(expId) {
  const query = useQuery({
    queryKey: ['experiment-detail', expId],
    queryFn: async () => {
      const { getExperiment } = await import('../api/client')
      return getExperiment(expId)
    },
    enabled: Boolean(expId),
  })

  return wrapQuery(query)
}

/**
 * Hook for experiment metrics.
 */
export function useExperimentMetrics(expId) {
  const query = useQuery({
    queryKey: ['experiment-metrics', expId],
    queryFn: async () => {
      const { getMetrics } = await import('../api/client')
      const raw = await getMetrics(expId)
      return normalizeMetrics(raw)
    },
    enabled: Boolean(expId),
  })

  return wrapQuery(query)
}

/**
 * Hook for experiment thermo data.
 */
export function useExperimentThermo(expId) {
  const query = useQuery({
    queryKey: ['experiment-thermo', expId],
    queryFn: async ({ signal }) => {
      const { getExperimentThermo } = await import('../api/client')
      return getExperimentThermo(expId, signal)
    },
    enabled: Boolean(expId),
  })

  return wrapQuery(query)
}

/**
 * Hook for delete experiment.
 */
export function useDeleteExperiment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (expId) => {
      const { deleteExperiment } = await import('../api/client')
      return deleteExperiment(expId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
    },
  })
}

/**
 * Hook for cancel experiment.
 */
export function useCancelExperiment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (expId) => {
      const { cancelExperiment } = await import('../api/client')
      return cancelExperiment(expId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
      queryClient.invalidateQueries({ queryKey: ['running-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

/**
 * Hook for retry experiment.
 */
export function useRetryExperiment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (expId) => {
      const { retryExperiment } = await import('../api/client')
      return retryExperiment(expId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
      queryClient.invalidateQueries({ queryKey: ['running-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

/**
 * Hook for batch cancel experiments.
 */
export function useBatchCancelExperiments() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (expIds) => {
      const { batchCancelExperiments } = await import('../api/client')
      return batchCancelExperiments(expIds)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
      queryClient.invalidateQueries({ queryKey: ['running-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

/**
 * Hook for batch delete experiments.
 */
export function useBatchDeleteExperiments() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (expIds) => {
      const { batchDeleteExperiments } = await import('../api/client')
      return batchDeleteExperiments(expIds)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
      queryClient.invalidateQueries({ queryKey: ['layered-experiments'] })
    },
  })
}

/**
 * Hook for batch retry experiments.
 */
export function useBatchRetryExperiments() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (expIds) => {
      const { batchRetryExperiments } = await import('../api/client')
      return batchRetryExperiments(expIds)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
      queryClient.invalidateQueries({ queryKey: ['running-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

/**
 * Hook for submit experiment.
 */
export function useSubmitExperiment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (payload) => {
      const { submitExperiment } = await import('../api/client')
      return submitExperiment(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
      queryClient.invalidateQueries({ queryKey: ['running-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

/**
 * Hook for experiment defaults (temperature SSOT, etc.).
 * Fetched once and cached — no polling needed.
 */
export function useExperimentDefaults() {
  const query = useQuery({
    queryKey: ['experiment-defaults'],
    queryFn: async () => {
      const { getExperimentDefaults } = await import('../api/experiments')
      return getExperimentDefaults()
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  return {
    data: query.data,
    loading: query.isLoading,
  }
}

/**
 * Hook for experiment filter options (tiers, additive types, temperature range).
 * Fetched once and cached.
 */
export function useExperimentFilterOptions() {
  const query = useQuery({
    queryKey: ['experiment-filter-options'],
    queryFn: async () => {
      const { getExperimentFilterOptions } = await import('../api/client')
      return getExperimentFilterOptions()
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for submitting single-molecule E_intra batch jobs.
 */
export function useSubmitSingleMoleculeBatch() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (payload) => {
      const { submitSingleMoleculeBatch } = await import('../api/client')
      return submitSingleMoleculeBatch(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
      queryClient.invalidateQueries({ queryKey: ['running-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}
