/**
 * React Query hooks for the Analysis Explorer API.
 */
import { useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

export function useExplorerCatalog() {
  const query = useQuery({
    queryKey: ['explorer-catalog'],
    queryFn: async () => {
      const { getExplorerCatalog } = await import('../api/analysisExplorer')
      return getExplorerCatalog()
    },
    staleTime: 5 * 60 * 1000,
  })
  return wrapQuery(query)
}

export function useExplorerData(request, enabled = true) {
  const query = useQuery({
    queryKey: ['explorer-data', JSON.stringify(request)],
    queryFn: async () => {
      const { postExplorerData } = await import('../api/analysisExplorer')
      return postExplorerData(request)
    },
    enabled: enabled && !!request?.dataset_mode,
    refetchInterval: 60000,
    refetchIntervalInBackground: false,
  })
  return wrapQuery(query)
}

export function useExplorerAggregate(request, enabled = true) {
  const query = useQuery({
    queryKey: ['explorer-aggregate', JSON.stringify(request)],
    queryFn: async () => {
      const { postExplorerAggregate } = await import('../api/analysisExplorer')
      return postExplorerAggregate(request)
    },
    enabled: enabled && !!request?.dataset_mode && !!request?.metric,
    refetchInterval: 60000,
    refetchIntervalInBackground: false,
  })
  return wrapQuery(query)
}
