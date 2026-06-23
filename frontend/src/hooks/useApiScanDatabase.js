import { useMutation, useQueryClient } from '@tanstack/react-query'

export function useScanDatabase() {
  return useMutation({
    mutationFn: async () => {
      const { scanDatabase } = await import('../api/client')
      return scanDatabase()
    },
  })
}

export function useImportExperiments() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data) => {
      const { importExperiments } = await import('../api/client')
      return importExperiments(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['molecules'] })
      queryClient.invalidateQueries({ queryKey: ['e-intra'] })
      queryClient.invalidateQueries({ queryKey: ['layered-experiments'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
    },
  })
}

export function useDeleteScannedExperiments() {
  return useMutation({
    mutationFn: async (data) => {
      const { deleteScannedExperiments } = await import('../api/client')
      return deleteScannedExperiments(data)
    },
  })
}
