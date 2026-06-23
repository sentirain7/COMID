import { useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'
import { createMutationHook } from './useMutationFactory'

/**
 * Hook for jobs list with polling.
 */
export function useJobs(interval = 3000) {
  const query = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const { listJobs } = await import('../api/client')
      return listJobs()
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

const jobInvalidationKeys = [['jobs'], ['queue-stats'], ['running-jobs']]

const deleteJobMutation = async (jobId) => {
  const { deleteJob } = await import('../api/client')
  return deleteJob(jobId)
}

const cancelJobMutation = async (jobId) => {
  const { cancelJob } = await import('../api/client')
  return cancelJob(jobId)
}

const retryJobMutation = async (jobId) => {
  const { retryJob } = await import('../api/client')
  return retryJob(jobId)
}

const deleteAllCompletedJobsMutation = async () => {
  const { deleteAllCompletedJobs } = await import('../api/client')
  return deleteAllCompletedJobs()
}

export const useDeleteJob = createMutationHook(deleteJobMutation, jobInvalidationKeys)
export const useCancelJob = createMutationHook(cancelJobMutation, jobInvalidationKeys)
export const useRetryJob = createMutationHook(retryJobMutation, jobInvalidationKeys)
export const useDeleteAllCompletedJobs = createMutationHook(
  deleteAllCompletedJobsMutation,
  jobInvalidationKeys,
)
