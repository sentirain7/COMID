import { useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

/**
 * Hook for health check.
 */
export function useHealth(interval = 10000) {
  const query = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const { getHealth } = await import('../api/client')
      return getHealth()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for GPU stats with polling.
 */
export function useGPUStats(interval = 3000) {
  const query = useQuery({
    queryKey: ['gpu-stats'],
    queryFn: async () => {
      const { getGPUStats } = await import('../api/client')
      return getGPUStats()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for running jobs with polling.
 */
export function useRunningJobs(interval = 2000) {
  const query = useQuery({
    queryKey: ['running-jobs'],
    queryFn: async () => {
      const { getRunningJobs } = await import('../api/client')
      return getRunningJobs()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for system stats (CPU, Memory) with polling.
 */
export function useSystemStats(interval = 5000) {
  const query = useQuery({
    queryKey: ['system-stats'],
    queryFn: async () => {
      const { getSystemStats } = await import('../api/client')
      return getSystemStats()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}
