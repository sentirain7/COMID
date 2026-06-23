import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'
import { createMutationHook } from './useMutationFactory'

export function useBinderStudies(filters = {}, interval = 10000) {
  const filterKey = useMemo(() => JSON.stringify(filters || {}), [filters])
  const query = useQuery({
    queryKey: ['binder-studies', filterKey],
    queryFn: async () => {
      const { listBinderStudies } = await import('../api/client')
      return listBinderStudies(filters?.state)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

export function useBinderStudyDetail(studyId, interval = 5000) {
  const query = useQuery({
    queryKey: ['binder-study-detail', studyId],
    enabled: Boolean(studyId),
    queryFn: async () => {
      const { getBinderStudy } = await import('../api/client')
      return getBinderStudy(studyId)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

export function useBinderStudyResults(studyId, interval = 10000) {
  const query = useQuery({
    queryKey: ['binder-study-results', studyId],
    enabled: Boolean(studyId),
    queryFn: async () => {
      const { getBinderStudyResults } = await import('../api/client')
      return getBinderStudyResults(studyId)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

export const useDeleteBinderStudy = createMutationHook(
  async (studyId) => {
    const { deleteBinderStudy } = await import('../api/client')
    return deleteBinderStudy(studyId)
  },
  [['binder-studies'], ['binder-study-detail'], ['binder-study-results']],
)
