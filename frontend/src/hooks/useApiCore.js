import { useQuery, useQueryClient } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

/**
 * Generic hook for one-shot API calls with loading and error states.
 */
export function useApi(apiFunction, dependencies = [], immediate = true) {
  const queryKey = ['api', apiFunction?.name || 'anonymous', ...dependencies]
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey,
    queryFn: () => apiFunction(),
    enabled: immediate,
  })

  const setData = (updater) => {
    queryClient.setQueryData(queryKey, updater)
  }

  return {
    ...wrapQuery(query),
    setData,
  }
}

/**
 * Hook for polling data at regular intervals.
 */
export function usePolling(apiFunction, interval = 5000, dependencies = []) {
  const query = useQuery({
    queryKey: ['poll', apiFunction?.name || 'anonymous', ...dependencies],
    queryFn: () => apiFunction(),
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}
