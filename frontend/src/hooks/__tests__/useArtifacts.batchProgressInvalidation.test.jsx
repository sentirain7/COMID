/**
 * v00.99.56 — useAdminBatchProgress tick-based invalidation contract.
 *
 * During a running batch, every polling tick that reports a newly
 * completed or failed mol must refresh downstream caches so the FF
 * badge / E_intra / Preview surfaces reflect partial progress without
 * waiting for `running: true → false`.
 *
 * Pins:
 *   - full invalidate on batch end (running: true → false) — 3 keys
 *   - partial invalidate on completed/failed increment — 2 keys,
 *     ['molecules'] uses predicate that excludes 'totals', and
 *     ['artifact-status'] (public) is NOT invalidated
 *   - no invalidate when counts are unchanged
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({
  default: {},
  getAdminBatchProgress: vi.fn(() =>
    Promise.resolve({ running: false, completed: 0, failed: 0 }),
  ),
  // Unused in this test but imported transitively by useArtifacts.
  adminGenerateArtifact: vi.fn(),
  adminGenerateAll: vi.fn(),
  adminCancelBatch: vi.fn(),
  adminGenerateSelected: vi.fn(),
  adminDiagnoseArtifact: vi.fn(),
  getAdminArtifactStatus: vi.fn(),
  deleteArtifact: vi.fn(),
  deleteEIntra: vi.fn(),
}))

import { getAdminBatchProgress } from '../../api/client'
import { useAdminBatchProgress } from '../useArtifacts'

function makeHarness() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnMount: false } },
  })
  // Seed adjacent caches so invalidate calls resolve against real queries.
  qc.setQueryData(['molecules', { limit: 500 }], { molecules: [] })
  qc.setQueryData(['molecules', 'totals'], { molecules: [] })
  qc.setQueryData(['artifact-admin-status'], { rows: [] })
  qc.setQueryData(['artifact-status'], { ff_parameters: {} })

  const calls = []
  const original = qc.invalidateQueries.bind(qc)
  qc.invalidateQueries = (args) => {
    calls.push(args)
    return original(args)
  }

  function Wrapper({ children }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }

  function setProgress(data) {
    vi.mocked(getAdminBatchProgress).mockResolvedValue(data)
    qc.setQueryData(['artifact-admin-batch-progress'], data)
  }

  return { qc, Wrapper, calls, setProgress }
}

const keyOf = (c) => JSON.stringify(c.queryKey)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useAdminBatchProgress — tick invalidation contract', () => {
  test('running → idle transition fires full 3-key invalidate (no predicate)', async () => {
    const { Wrapper, calls, setProgress } = makeHarness()
    setProgress({ running: true, completed: 1, failed: 0 })
    const { rerender } = renderHook(() => useAdminBatchProgress(true), {
      wrapper: Wrapper,
    })
    // Clear any initial-mount invalidation bookkeeping.
    calls.length = 0

    setProgress({ running: false, completed: 1, failed: 0 })
    rerender()

    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(3))
    const keys = calls.map(keyOf)
    expect(keys).toContain(JSON.stringify(['artifact-admin-status']))
    expect(keys).toContain(JSON.stringify(['artifact-status']))
    expect(keys).toContain(JSON.stringify(['molecules']))
    // Full invalidate must NOT use a predicate (refresh totals too).
    const moleculesCall = calls.find(
      (c) => keyOf(c) === JSON.stringify(['molecules']),
    )
    expect(moleculesCall.predicate).toBeUndefined()
  })

  test('completed increment while running fires partial invalidate (2 keys, predicate)', async () => {
    const { Wrapper, calls, setProgress } = makeHarness()
    setProgress({ running: true, completed: 0, failed: 0 })
    renderHook(() => useAdminBatchProgress(true), { wrapper: Wrapper })
    calls.length = 0

    setProgress({ running: true, completed: 1, failed: 0 })

    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2))
    const keys = calls.map(keyOf)
    expect(keys).toContain(JSON.stringify(['artifact-admin-status']))
    expect(keys).toContain(JSON.stringify(['molecules']))
    // Public status must stay intact during partial ticks.
    expect(keys).not.toContain(JSON.stringify(['artifact-status']))

    const moleculesCall = calls.find(
      (c) => keyOf(c) === JSON.stringify(['molecules']),
    )
    expect(typeof moleculesCall.predicate).toBe('function')
    // Predicate keeps filtered molecules caches.
    expect(
      moleculesCall.predicate({ queryKey: ['molecules', { limit: 500 }] }),
    ).toBe(true)
    // Predicate excludes the 'totals' query (aggregates unchanged mid-batch).
    expect(
      moleculesCall.predicate({ queryKey: ['molecules', 'totals'] }),
    ).toBe(false)
  })

  test('failed increment while running also triggers partial invalidate', async () => {
    const { Wrapper, calls, setProgress } = makeHarness()
    setProgress({ running: true, completed: 0, failed: 0 })
    renderHook(() => useAdminBatchProgress(true), { wrapper: Wrapper })
    calls.length = 0

    setProgress({ running: true, completed: 0, failed: 1 })

    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2))
    const keys = calls.map(keyOf)
    expect(keys).toContain(JSON.stringify(['artifact-admin-status']))
    expect(keys).toContain(JSON.stringify(['molecules']))
    expect(keys).not.toContain(JSON.stringify(['artifact-status']))
  })

  test('tick with unchanged completed/failed does not invalidate', async () => {
    const { Wrapper, calls, setProgress } = makeHarness()
    setProgress({ running: true, completed: 2, failed: 1 })
    renderHook(() => useAdminBatchProgress(true), { wrapper: Wrapper })
    calls.length = 0

    // New object, identical counts: the else-if condition must not fire.
    setProgress({ running: true, completed: 2, failed: 1 })

    await new Promise((r) => setTimeout(r, 30))
    expect(calls).toHaveLength(0)
  })
})
