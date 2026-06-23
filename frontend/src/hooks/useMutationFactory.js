import { useMutation, useQueryClient } from '@tanstack/react-query'

export function createMutationHook(mutationFn, invalidateKeys = []) {
  return function useMutationHook() {
    const queryClient = useQueryClient()

    return useMutation({
      mutationFn,
      onSuccess: () => {
        invalidateKeys.forEach((key) => {
          queryClient.invalidateQueries({ queryKey: key })
        })
      },
    })
  }
}
