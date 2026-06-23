import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useQueueStatsLive } from '../useApi'

vi.mock('../../api/client', () => ({
  getQueueStats: vi.fn(),
}))

describe('useQueueStatsLive', () => {
  let queryClient

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })
  })

  afterEach(() => {
    queryClient.clear()
    vi.clearAllMocks()
  })

  const createWrapper = () =>
    function Wrapper({ children }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

  it('polls the REST queue-stats endpoint and exposes data under the queue-stats cache key', async () => {
    const { getQueueStats } = await import('../../api/client')
    getQueueStats.mockResolvedValue({
      total_pending: 1,
      total_queued: 2,
      building: 7,
      total_running: 3,
      analyzing: 4,
      total_completed: 5,
      total_failed: 0,
      total_cancelled: 6,
      total_timeout: 9,
      atoms_in_progress: 100,
      jobs_by_tier: {},
      jobs_by_queue: {},
      completed_today: 11,
      completed_this_week: 22,
    })

    const { result } = renderHook(() => useQueueStatsLive(3000), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(getQueueStats).toHaveBeenCalled()
    expect(result.current.data.total_pending).toBe(1)
    expect(result.current.data.building).toBe(7)
    expect(result.current.data.completed_this_week).toBe(22)
    expect(queryClient.getQueryData(['queue-stats'])).toEqual(result.current.data)
  })

  it('shares the queue-stats cache with useQueueStats consumers', async () => {
    const { getQueueStats } = await import('../../api/client')
    getQueueStats.mockResolvedValue({
      total_pending: 3,
      total_queued: 4,
      total_running: 5,
      total_completed: 6,
      total_failed: 0,
    })

    const { result } = renderHook(() => useQueueStatsLive(3000), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data.total_pending).toBe(3)
    expect(queryClient.getQueryData(['queue-stats']).total_completed).toBe(6)
  })
})
