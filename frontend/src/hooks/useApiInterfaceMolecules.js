import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

// Molecule catalog hooks
export function useInterfaceMolecules() {
  const query = useQuery({
    queryKey: ['interface-molecules'],
    queryFn: async () => {
      const { listInterfaceMolecules } = await import('../api/client')
      return listInterfaceMolecules()
    },
  })
  return wrapQuery(query)
}

export function useInterfaceMoleculePreview(molId, enabled = true) {
  const query = useQuery({
    queryKey: ['interface-molecule-preview', molId],
    enabled: Boolean(molId) && enabled,
    queryFn: async () => {
      const { getInterfaceMoleculePreview } = await import('../api/client')
      return getInterfaceMoleculePreview(molId)
    },
  })
  return wrapQuery(query)
}

// Cell library hooks
export function useInterfaceMoleculeCells(filters = {}) {
  const filterKey = useMemo(() => JSON.stringify(filters || {}), [filters])
  const query = useQuery({
    queryKey: ['interface-molecule-cells', filterKey],
    queryFn: async () => {
      const { listInterfaceMoleculeCells } = await import('../api/client')
      return listInterfaceMoleculeCells(filters || {})
    },
  })
  return wrapQuery(query)
}

export function useInterfaceMoleculeCellPreview(cellId, enabled = true) {
  const query = useQuery({
    queryKey: ['interface-molecule-cell-preview', cellId],
    enabled: Boolean(cellId) && enabled,
    queryFn: async () => {
      const { getInterfaceMoleculeCellPreview } = await import('../api/client')
      return getInterfaceMoleculeCellPreview(cellId)
    },
  })
  return wrapQuery(query)
}

export function useCreateInterfaceMoleculeCell() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { createInterfaceMoleculeCell } = await import('../api/client')
      return createInterfaceMoleculeCell(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interface-molecule-cells'] })
    },
  })
}

export function useDeleteInterfaceMoleculeCell() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (cellId) => {
      const { deleteInterfaceMoleculeCell } = await import('../api/client')
      return deleteInterfaceMoleculeCell(cellId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interface-molecule-cells'] })
    },
  })
}

export function useBatchGenerateInterfaceMoleculeCells() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { batchGenerateInterfaceMoleculeCells } = await import('../api/client')
      return batchGenerateInterfaceMoleculeCells(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interface-molecule-cells'] })
    },
  })
}
