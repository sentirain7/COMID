import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSubmitSingleMoleculeBatch } from '../useApiExperiments'

vi.mock('../../api/client', () => ({
  submitSingleMoleculeBatch: vi.fn(async () => ({
    mol_id: 'U-AS-Thio-0293',
    total: 1,
    submitted: 1,
    skipped_existing: 0,
    failed: 0,
    items: [{ temperature_K: 293, status: 'submitted', exp_id: 'exp_001', error: null }],
    resolved_ff_hint: 'gaff2',
    resolved_ff_display_label: 'GAFF2',
  })),
}))

describe('useSubmitSingleMoleculeBatch', () => {
  let queryClient
  let invalidateSpy

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  })

  afterEach(() => {
    queryClient.clear()
    vi.clearAllMocks()
  })

  const createWrapper = () =>
    function Wrapper({ children }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

  it('does NOT invalidate molecules query on success', async () => {
    const { result } = renderHook(() => useSubmitSingleMoleculeBatch(), {
      wrapper: createWrapper(),
    })

    await result.current.mutateAsync({
      selected_mol_id: 'U-AS-Thio-0293',
      temperatures_k: [293],
      seed: 20260101,
      force_recompute: false,
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalled()
    })

    const invalidatedKeys = invalidateSpy.mock.calls.map((call) => call[0]?.queryKey?.[0])
    expect(invalidatedKeys).not.toContain('molecules')
  })

  it('invalidates experiments, queue-stats, running-jobs, jobs on success', async () => {
    const { result } = renderHook(() => useSubmitSingleMoleculeBatch(), {
      wrapper: createWrapper(),
    })

    await result.current.mutateAsync({
      selected_mol_id: 'U-AS-Thio-0293',
      temperatures_k: [293],
      seed: 20260101,
      force_recompute: false,
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalled()
    })

    const invalidatedKeys = invalidateSpy.mock.calls.map((call) => call[0]?.queryKey?.[0])
    expect(invalidatedKeys).toContain('experiments')
    expect(invalidatedKeys).toContain('queue-stats')
    expect(invalidatedKeys).toContain('running-jobs')
    expect(invalidatedKeys).toContain('jobs')
  })
})
