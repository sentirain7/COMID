import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

// Lifecycle event order matching the former realtime event stream.
const STANDARD_EVENT_ORDER = ['build_started', 'build_done', 'run_scheduled', 'run_started']

// Map a DB experiment status to the lifecycle events that must already have
// happened to reach that status (prefix of STANDARD_EVENT_ORDER).
const STATUS_TIMELINE = {
  building: 1, // build_started
  ready: 2, // + build_done
  running: 4, // + run_scheduled + run_started
}

/**
 * Hook for per-experiment lifecycle timelines via REST polling.
 *
 * Formerly backed by the GraphQL `experimentUpdates` WebSocket subscription.
 * Now polls GET /experiments and derives the lifecycle timeline for each
 * active experiment from its DB status (DB status is SSOT).
 *
 * @param {number} interval - Polling interval in ms (default 3000, matching useQueueStats)
 * @returns {{ eventsByExp: Object }} Map of exp_id -> ordered lifecycle events
 */
export function useExperimentEvents(interval = 3000) {
  const { data } = useQuery({
    queryKey: ['experiment-events'],
    queryFn: async () => {
      const { listExperiments } = await import('../api/client')
      return listExperiments({ limit: 1000 })
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  const eventsByExp = useMemo(() => {
    const experiments = data?.experiments || []
    const result = {}
    for (const exp of experiments) {
      if (!exp?.exp_id) continue
      const status = String(exp.status || '').toLowerCase()
      const prefixLength = STATUS_TIMELINE[status]
      if (!prefixLength) continue
      const timestamp = exp.updated_at || exp.created_at || null
      result[exp.exp_id] = STANDARD_EVENT_ORDER.slice(0, prefixLength).map((eventType) => ({
        eventType,
        expId: exp.exp_id,
        status,
        message: null,
        timestamp,
      }))
    }
    return result
  }, [data])

  return { eventsByExp }
}
