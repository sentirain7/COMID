import { useQuery } from '@tanstack/react-query'
// Import the domain module directly — to avoid affecting existing tests that partially mock
// the api/client barrel (the barrel re-export is kept in client.js).
import {
  approveInversePlan,
  getInversePipelineProgress,
  getInversePipelineResults,
  previewInversePlan,
} from '../api/inversePipeline'
import { createMutationHook } from './useMutationFactory'

// Inverse-design pipeline hooks (wizard ①~④)

export const usePreviewInversePlan = createMutationHook(previewInversePlan)

export const useApproveInversePlan = createMutationHook(approveInversePlan, [
  ['inverse-pipeline'],
  ['api', 'listExperiments'],
])

export function useInversePipelineProgress(pipelineId, { refetchInterval = 3000 } = {}) {
  return useQuery({
    queryKey: ['inverse-pipeline', pipelineId, 'progress'],
    queryFn: () => getInversePipelineProgress(pipelineId),
    enabled: Boolean(pipelineId),
    refetchInterval,
    refetchIntervalInBackground: false,
  })
}

export function useInversePipelineResults(pipelineId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['inverse-pipeline', pipelineId, 'results'],
    queryFn: () => getInversePipelineResults(pipelineId),
    enabled: Boolean(pipelineId) && enabled,
  })
}
