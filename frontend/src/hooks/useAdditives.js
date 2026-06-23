import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listAdditives } from '../api/client'

export function useAdditives() {
  const query = useQuery({
    queryKey: ['additives'],
    queryFn: () => listAdditives(),
  })

  const additives = useMemo(() => query.data?.additives || [], [query.data])

  const catalog = useMemo(
    () =>
      additives.reduce((acc, item) => {
        if (item?.mol_id) acc[item.mol_id] = item
        return acc
      }, {}),
    [additives]
  )

  return {
    additives,
    catalog,
    loading: query.isLoading,
    error: query.error,
  }
}

export default useAdditives
