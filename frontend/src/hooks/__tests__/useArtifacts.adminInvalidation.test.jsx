/**
 * v00.99.43 Phase B — admin mutation 4-key invalidation contract.
 *
 * Codex's audit caught us missing ['molecules'] from the admin
 * mutations' invalidation set, which left the public Molecules page
 * stale after admin actions. This test pins the four keys every admin
 * mutation must invalidate so a future regression is caught here.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({
  default: {},
  adminGenerateArtifact: vi.fn(() => Promise.resolve({ status: 'completed' })),
  adminGenerateAll: vi.fn(() =>
    Promise.resolve({ status: 'accepted', batch_kind: 'admin' }),
  ),
  adminGenerateSelected: vi.fn(() =>
    Promise.resolve({ status: 'accepted', batch_kind: 'admin' }),
  ),
  adminCancelBatch: vi.fn(() => Promise.resolve({ status: 'cancelling' })),
  adminDiagnoseArtifact: vi.fn(() => Promise.resolve({ verdict: 'ok' })),
  getAdminBatchProgress: vi.fn(() => Promise.resolve({ running: false })),
  getAdminArtifactStatus: vi.fn(() =>
    Promise.resolve({ rows: [], conflicts: [] }),
  ),
  deleteArtifact: vi.fn(),
  deleteEIntra: vi.fn(),
}))

import {
  useAdminCancelBatch,
  useAdminGenerateAll,
  useAdminGenerateArtifact,
} from '../useArtifacts'

const EXPECTED_INVALIDATION_KEYS = [
  ['artifact-admin-status'],
  ['artifact-admin-batch-progress'],
  ['artifact-status'],
  ['molecules'],
]

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const invalidations = []
  const originalInvalidate = qc.invalidateQueries.bind(qc)
  qc.invalidateQueries = (args) => {
    invalidations.push(args.queryKey)
    return originalInvalidate(args)
  }
  function Wrapper({ children }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
  return { Wrapper, invalidations }
}

beforeEach(() => {
  vi.clearAllMocks()
})

function _assertExpectedKeys(invalidations) {
  // Each expected key must appear at least once in the invalidation log.
  for (const expected of EXPECTED_INVALIDATION_KEYS) {
    expect(invalidations).toContainEqual(expected)
  }
}

describe('admin mutation 4-key invalidation contract', () => {
  test('useAdminGenerateArtifact invalidates all four caches', async () => {
    const { Wrapper, invalidations } = makeWrapper()
    const { result } = renderHook(() => useAdminGenerateArtifact(), {
      wrapper: Wrapper,
    })
    await result.current.mutateAsync({ molId: 'Toluene', profile: 'baseline' })
    await waitFor(() => expect(invalidations.length).toBeGreaterThanOrEqual(4))
    _assertExpectedKeys(invalidations)
  })

  test('useAdminGenerateAll invalidates all four caches', async () => {
    const { Wrapper, invalidations } = makeWrapper()
    const { result } = renderHook(() => useAdminGenerateAll(), {
      wrapper: Wrapper,
    })
    await result.current.mutateAsync('baseline')
    await waitFor(() => expect(invalidations.length).toBeGreaterThanOrEqual(4))
    _assertExpectedKeys(invalidations)
  })

  test('useAdminGenerateAll accepts {profile} object argument (Molecules.jsx call shape)', async () => {
    // Regression for v00.99.54 — handleGenerateAll passes `{ profile: ffProfile }`.
    // Earlier (profile='baseline') signature stringified the whole object into
    // the query param, tripping the backend's profile allow-list validator.
    const { Wrapper, invalidations } = makeWrapper()
    const { result } = renderHook(() => useAdminGenerateAll(), {
      wrapper: Wrapper,
    })
    await result.current.mutateAsync({ profile: 'sqm_robust' })
    await waitFor(() => expect(invalidations.length).toBeGreaterThanOrEqual(4))
    _assertExpectedKeys(invalidations)
  })

  test('useAdminCancelBatch invalidates all four caches', async () => {
    const { Wrapper, invalidations } = makeWrapper()
    const { result } = renderHook(() => useAdminCancelBatch(), {
      wrapper: Wrapper,
    })
    await result.current.mutateAsync()
    await waitFor(() => expect(invalidations.length).toBeGreaterThanOrEqual(4))
    _assertExpectedKeys(invalidations)
  })
})
