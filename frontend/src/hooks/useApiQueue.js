import { useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

/**
 * Hook for queue stats with REST polling.
 */
export function useQueueStats(interval = 3000) {
  const query = useQuery({
    queryKey: ['queue-stats'],
    queryFn: async () => {
      const { getQueueStats } = await import('../api/client')
      return getQueueStats()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for queue stats with REST polling.
 *
 * Formerly backed by a GraphQL WebSocket subscription. The subscription
 * transport has been removed; this is now an alias of `useQueueStats`
 * kept so existing consumers keep working unchanged.
 */
export function useQueueStatsLive(interval = 3000) {
  return useQueueStats(interval)
}
