/**
 * useEIntraLive - E_intra cache refresh via REST polling.
 *
 * Formerly backed by the GraphQL `eIntraUpdates` WebSocket subscription.
 * E_intra rows are written exactly when a single-molecule vacuum experiment
 * completes, so this hook polls the lightweight GET /queue/stats endpoint
 * (shared React Query key `['queue-stats']`, deduplicated with the Dashboard
 * poller) and, whenever the completed-experiment count changes, invalidates
 * the molecule/E_intra caches so the UI refetches fresh values from
 * GET /molecules and GET /e_intra/{mol_id}.
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useQueueStats } from './useApiQueue'

/**
 * Hook that keeps E_intra-derived caches fresh while jobs complete.
 *
 * @param {string[]|null} molIds - Optional filter: also invalidate the
 *   per-molecule `['molecule', molId]` caches for these mol_ids
 * @param {number} interval - Polling interval in ms (default 5000)
 * @returns {{ latestUpdate: null }} Kept for interface compatibility with the
 *   former subscription hook; per-event payloads are no longer available.
 */
export function useEIntraLive(molIds = null, interval = 5000) {
  const queryClient = useQueryClient()
  const completedRef = useRef(null)
  const { data: stats } = useQueueStats(interval)
  const completedCount = stats?.total_completed ?? null

  useEffect(() => {
    if (completedCount == null) return
    if (completedRef.current === null) {
      // First observation: record the baseline without invalidating.
      completedRef.current = completedCount
      return
    }
    if (completedCount === completedRef.current) return
    completedRef.current = completedCount

    // A job finished since the last poll — refresh E_intra-derived caches.
    // Excludes the ['molecules', 'totals'] aggregate-counts query: totals are
    // derived from molecule structure, not E_intra rows.
    queryClient.invalidateQueries({
      predicate: (query) => {
        const [root, filters] = query.queryKey || []
        return root === 'molecules' && filters !== 'totals'
      },
    })
    queryClient.invalidateQueries({ queryKey: ['e-intra'] })
    for (const molId of molIds || []) {
      queryClient.invalidateQueries({ queryKey: ['molecule', molId] })
    }
  }, [completedCount, molIds, queryClient])

  return { latestUpdate: null }
}

export default useEIntraLive
