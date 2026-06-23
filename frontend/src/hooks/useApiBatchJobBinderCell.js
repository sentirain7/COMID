import { useMutation, useQueryClient } from '@tanstack/react-query'

/**
 * Hook to validate Batch Job / Binder Cell config.
 */
export function useValidateBatchJobBinderCell() {
  return useMutation({
    mutationFn: async (payload) => {
      const { validateBatchJobBinderCell } = await import('../api/client')
      return validateBatchJobBinderCell(payload)
    },
  })
}

/**
 * Hook to submit Batch Job / Binder Cell.
 */
export function useCreateBatchJobBinderCell() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (payload) => {
      const { createBatchJobBinderCell } = await import('../api/client')
      return createBatchJobBinderCell(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
    },
  })
}
