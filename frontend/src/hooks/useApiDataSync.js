import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export function useScanAssets() {
  return useMutation({
    mutationFn: async (assetType) => {
      const { scanAssets } = await import('../api/dataSync')
      return scanAssets(assetType)
    },
  })
}

export function useImportAssets() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data) => {
      const { importAssets } = await import('../api/dataSync')
      return importAssets(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interface-molecule-cells'] })
      queryClient.invalidateQueries({ queryKey: ['crystal-structures'] })
      queryClient.invalidateQueries({ queryKey: ['molecules'] })
    },
  })
}

export function useBackupToNas() {
  return useMutation({
    mutationFn: async (assetTypes) => {
      const { backupToNas } = await import('../api/dataSync')
      return backupToNas(assetTypes)
    },
  })
}

export function useLoadFromNas() {
  return useMutation({
    mutationFn: async (manifestPath) => {
      const { loadFromNas } = await import('../api/dataSync')
      return loadFromNas(manifestPath)
    },
  })
}

export function useApplyNasLoad() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data) => {
      const { applyNasLoad } = await import('../api/dataSync')
      return applyNasLoad(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interface-molecule-cells'] })
      queryClient.invalidateQueries({ queryKey: ['crystal-structures'] })
      queryClient.invalidateQueries({ queryKey: ['molecules'] })
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
    },
  })
}

export function useNasStatus() {
  const query = useQuery({
    queryKey: ['nas-status'],
    queryFn: async () => {
      const { getNasStatus } = await import('../api/dataSync')
      return getNasStatus()
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })

  return {
    data: query.data,
    loading: query.isLoading,
  }
}
