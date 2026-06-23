import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listBinderTypes } from '../api/client'
import { FALLBACK_BINDER_TYPES, FALLBACK_BINDER_TYPE_NAMES } from '../lib/constants'

export function useBinderTypes({ asObjects = false } = {}) {
  const query = useQuery({
    queryKey: ['binder-types'],
    queryFn: () => listBinderTypes(),
  })

  const binderTypes = useMemo(() => {
    const raw = query.data?.binder_types || []
    if (asObjects) {
      const options = raw.filter(Boolean)
      return options.length > 0 ? options : FALLBACK_BINDER_TYPES
    }
    const names = raw.map((item) => item?.name).filter(Boolean)
    return names.length > 0 ? names : FALLBACK_BINDER_TYPE_NAMES
  }, [query.data, asObjects])

  return {
    binderTypes,
    loading: query.isLoading,
    error: query.error,
  }
}

export default useBinderTypes
