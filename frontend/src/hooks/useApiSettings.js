import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toErrorMessage, wrapQuery } from './useApiShared'
import { createMutationHook } from './useMutationFactory'
import {
  getDefaultSubmissionEIntraMethod,
  withSubmissionDefaultEIntraMethod,
} from '../lib/eIntraMethod'

/**
 * Hook for recovery check.
 */
export function useRecoveryCheck() {
  const query = useQuery({
    queryKey: ['recovery-check'],
    queryFn: async () => {
      const { getRecoveryCheck } = await import('../api/client')
      return getRecoveryCheck()
    },
  })

  return wrapQuery(query)
}

/**
 * Hook for recovery candidates.
 */
export function useRecoveryCandidates(enabled = true) {
  const query = useQuery({
    queryKey: ['recovery-candidates'],
    queryFn: async () => {
      const { getRecoveryCandidates } = await import('../api/client')
      return getRecoveryCandidates()
    },
    enabled,
  })

  return wrapQuery(query)
}

const recoveryInvalidationKeys = [['recovery-candidates'], ['recovery-check']]

const executeRecoveryActionMutation = async ({ exp_id, action }) => {
  const { executeRecoveryAction } = await import('../api/client')
  return executeRecoveryAction({ exp_id, action })
}

const executeAllRecoveryActionsMutation = async () => {
  const { executeAllRecoveryActions } = await import('../api/client')
  return executeAllRecoveryActions()
}

export const useExecuteRecoveryAction = createMutationHook(
  executeRecoveryActionMutation,
  recoveryInvalidationKeys,
)

export const useExecuteAllRecoveryActions = createMutationHook(
  executeAllRecoveryActionsMutation,
  recoveryInvalidationKeys,
)

/**
 * Hook for settings (load once + update function).
 */
export function useSettings() {
  const queryClient = useQueryClient()

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { getSettings } = await import('../api/client')
      try {
        const settings = await getSettings()
        return withSubmissionDefaultEIntraMethod(settings, { useLocalFallback: false })
      } catch (_err) {
        return withSubmissionDefaultEIntraMethod({}, { useLocalFallback: true })
      }
    },
  })

  const updateMutation = useMutation({
    mutationFn: async (newSettings) => {
      const currentSettings = queryClient.getQueryData(['settings'])
      const hasEIntraMethod = Object.hasOwn(newSettings, 'default_e_intra_method')
      const defaultEIntraMethod = hasEIntraMethod
        ? getDefaultSubmissionEIntraMethod(newSettings.default_e_intra_method)
        : null

      const serverSettings = {
        ...newSettings,
        ...(defaultEIntraMethod ? { default_e_intra_method: defaultEIntraMethod } : {}),
      }

      if (Object.keys(serverSettings).length === 0) {
        return withSubmissionDefaultEIntraMethod({
          ...(currentSettings || {}),
          ...(defaultEIntraMethod ? { default_e_intra_method: defaultEIntraMethod } : {}),
        }, { useLocalFallback: false })
      }

      const { updateSettings } = await import('../api/client')
      const result = await updateSettings(serverSettings)
      return withSubmissionDefaultEIntraMethod({
        ...(currentSettings || {}),
        ...(result?.settings || result || {}),
        ...(defaultEIntraMethod ? { default_e_intra_method: defaultEIntraMethod } : {}),
      }, { useLocalFallback: false })
    },
    onSuccess: (result) => {
      queryClient.setQueryData(['settings'], result)
    },
  })

  return {
    settings: settingsQuery.data ?? null,
    loading: settingsQuery.isLoading || updateMutation.isPending,
    error: settingsQuery.error ? toErrorMessage(settingsQuery.error) : null,
    update: updateMutation.mutateAsync,
  }
}
