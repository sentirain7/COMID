import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'
import { createMutationHook } from './useMutationFactory'

/**
 * Hook for champion model.
 */
export function useChampionModel(interval = 15000) {
  const query = useQuery({
    queryKey: ['ml-champion'],
    queryFn: async () => {
      const { getChampionModel } = await import('../api/client')
      return getChampionModel()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for model history.
 */
export function useModelHistory(filters = {}, interval = 20000) {
  const filterKey = useMemo(() => JSON.stringify(filters), [filters])

  const query = useQuery({
    queryKey: ['ml-history', filterKey],
    queryFn: async () => {
      const { getModelHistory } = await import('../api/client')
      return getModelHistory(filters)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for drift check.
 */
export function useModelDrift(interval = 20000) {
  const query = useQuery({
    queryKey: ['ml-drift'],
    queryFn: async () => {
      const { checkModelDrift } = await import('../api/client')
      return checkModelDrift()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook to retrain model.
 */
const mlInvalidationKeys = [
  ['ml-champion'],
  ['ml-history'],
  ['ml-drift'],
  ['ml-data-coverage'],
  ['ml-data-quality'],
  ['ml-parity'],
  ['ml-feature-importance'],
  ['ml-residuals'],
  ['ml-learning-curve'],
]

const retrainModelMutation = async (payload) => {
  const { retrainModel } = await import('../api/client')
  return retrainModel(payload)
}

const promoteModelMutation = async (versionId) => {
  const { promoteModel } = await import('../api/client')
  return promoteModel(versionId)
}

const rollbackModelMutation = async () => {
  const { rollbackModel } = await import('../api/client')
  return rollbackModel()
}

export const useRetrainModel = createMutationHook(retrainModelMutation, mlInvalidationKeys)

/**
 * Hook to promote model.
 */
export const usePromoteModel = createMutationHook(promoteModelMutation, mlInvalidationKeys)

/**
 * Hook to rollback model.
 */
export const useRollbackModel = createMutationHook(rollbackModelMutation, mlInvalidationKeys)

/**
 * Hook for parity plot data.
 */
export function useParityPlot(target) {
  const query = useQuery({
    queryKey: ['ml-parity', target],
    queryFn: async () => {
      const { getParityPlot } = await import('../api/client')
      return getParityPlot(target)
    },
    enabled: !!target,
  })

  return wrapQuery(query)
}

/**
 * Hook for feature importance data.
 */
export function useFeatureImportance(target, topK = 15) {
  const query = useQuery({
    queryKey: ['ml-feature-importance', target, topK],
    queryFn: async () => {
      const { getFeatureImportance } = await import('../api/client')
      return getFeatureImportance(target, topK)
    },
    enabled: !!target,
  })

  return wrapQuery(query)
}

/**
 * Hook for residual distribution.
 */
export function useResiduals(target) {
  const query = useQuery({
    queryKey: ['ml-residuals', target],
    queryFn: async () => {
      const { getResiduals } = await import('../api/client')
      return getResiduals(target)
    },
    enabled: !!target,
  })

  return wrapQuery(query)
}

/**
 * Hook for learning curve data.
 */
export function useLearningCurve(target) {
  const query = useQuery({
    queryKey: ['ml-learning-curve', target],
    queryFn: async () => {
      const { getLearningCurve } = await import('../api/client')
      return getLearningCurve(target)
    },
    enabled: !!target,
  })

  return wrapQuery(query)
}

/**
 * Hook for data coverage diagnostics.
 */
export function useDataCoverage() {
  const query = useQuery({
    queryKey: ['ml-data-coverage'],
    queryFn: async () => {
      const { getDataCoverage } = await import('../api/client')
      return getDataCoverage()
    },
  })

  return wrapQuery(query)
}

/**
 * Hook for data quality diagnostics.
 */
export function useDataQuality() {
  const query = useQuery({
    queryKey: ['ml-data-quality'],
    queryFn: async () => {
      const { getDataQuality } = await import('../api/client')
      return getDataQuality()
    },
  })

  return wrapQuery(query)
}

/**
 * Hook for V7 structural ML opt-in status + champion feature-set.
 */
export function useStructuralMLStatus() {
  const query = useQuery({
    queryKey: ['ml-structural-status'],
    queryFn: async () => {
      const { getStructuralMLStatus } = await import('../api/client')
      return getStructuralMLStatus()
    },
  })

  return wrapQuery(query)
}

/**
 * Hook to run on-demand V7 XGB-vs-RF random-repeat evaluation.
 *
 * Mutation (not query) — triggered by the user via an explicit button. Since it includes
 * model training, the response can be slow, so it does not auto-poll.
 */
const runStructuralEvalMutation = async (payload) => {
  const { runStructuralEval } = await import('../api/client')
  return runStructuralEval(payload)
}

const runStructuralTrainMutation = async (payload) => {
  const { runStructuralTrain } = await import('../api/client')
  return runStructuralTrain(payload)
}

export const useStructuralEval = createMutationHook(runStructuralEvalMutation, [
  ['ml-structural-status'],
])

// Training can change the champion/status/diagnostics, so it invalidates the ML queries broadly.
export const useStructuralTrain = createMutationHook(runStructuralTrainMutation, [
  ['ml-structural-status'],
  ...mlInvalidationKeys,
])
