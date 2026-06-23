import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BatchJobBinderCell from '../BatchJobBinderCell'
import * as api from '../../api/client'

const mockCreateMutateAsync = vi.fn(async () => ({}))
const mockValidateMutate = vi.fn()

vi.mock('../../hooks/useApi', () => ({
  useValidateBatchJobBinderCell: () => ({ mutate: mockValidateMutate, isPending: false, data: null, error: null }),
  useCreateBatchJobBinderCell: () => ({ mutateAsync: mockCreateMutateAsync, isPending: false, data: null, error: null }),
  useSettings: () => ({
    settings: {
      default_tier: 'screening',
      default_e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
    },
    loading: false,
    error: null,
    update: vi.fn(),
  }),
  useEInterRecommendation: () => ({ data: null }),
}))

vi.mock('../../hooks/useApiExperiments', () => {
  const defaults = {
    data: {
      temperatures_k: [213, 233, 253, 273, 293, 313, 333],
      temperature_priority: [],
    },
    isLoading: false,
    error: null,
  }
  return {
    useExperimentDefaults: () => defaults,
  }
})

vi.mock('../../hooks/useAdditives', () => {
  const value = { additives: [], catalog: {} }
  return {
    default: () => value,
  }
})

vi.mock('../../hooks/useMoleculeWeights', () => {
  const value = { weightMap: {}, loading: false }
  return {
    default: () => value,
  }
})

vi.mock('../../api/client', () => ({
  precomputeTypingChargeCache: vi.fn(async () => ({
    ff_type: 'bulk_ff_gaff2',
    total_molecules: 10,
    unique_molecules: 2,
    cached: 0,
    computed: 2,
    failed: 0,
    details: [],
  })),
  listBinderTypes: vi.fn(async () => ({
    binder_types: [{ name: 'AAA1' }, { name: 'AAK1' }, { name: 'AAM1' }],
  })),
  listAdditives: vi.fn(async () => ({
    additives: [{ mol_id: 'SiO2', molecular_weight: 1177.51, default_counts: { X1: 2 } }],
  })),
  listMolecules: vi.fn(async () => ({ molecules: [] })),
  getBinderComposition: vi.fn(async () => ({ molecules: [] })),
  getDefaultStages: vi.fn(async () => ({
    stages: [
      { name: 'minimize', duration_ps: 0 },
      { name: 'nvt_equilibration', duration_ps: 300 },
      { name: 'npt_production', duration_ps: 2000 },
    ],
  })),
}))

describe('BatchJobBinderCell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without crashing', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <BatchJobBinderCell />
      </QueryClientProvider>
    )
    await waitFor(() => {
      expect(screen.getByText('Batch Job / Binder Cell')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Precompute/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/Typing\/Charge Cache/i)).not.toBeInTheDocument()
  })

  it('toggles temperature box selection on click', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <BatchJobBinderCell />
      </QueryClientProvider>
    )
    await waitFor(() => {
      expect(screen.getByText('Batch Job / Binder Cell')).toBeInTheDocument()
    })

    const button213 = screen
      .getAllByRole('button')
      .find((button) => button.textContent?.trim() === '213K')

    expect(button213).toBeTruthy()

    // 213K is in FALLBACK_TEMPERATURES_K → starts selected
    expect(button213).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(button213)
    await waitFor(() => {
      expect(button213).toHaveAttribute('aria-pressed', 'false')
    })
    fireEvent.click(button213)
    await waitFor(() => {
      expect(button213).toHaveAttribute('aria-pressed', 'true')
    })
  })

  it('does NOT call precomputeTypingChargeCache on submit (P0/P1 flow)', async () => {
    // P0/P1: Submit goes directly to create endpoint — NO precompute cache call.
    // Backend FF gate returns ff_blocked_items if artifacts are missing.
    // Users must generate artifacts via Molecules catalog BEFORE submit.

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <BatchJobBinderCell />
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('Batch Job / Binder Cell')).toBeInTheDocument()
    })

    // Clear any previous calls
    api.precomputeTypingChargeCache.mockClear()

    // Click Submit button
    fireEvent.click(screen.getByRole('button', { name: /Submit Batch Job/i }))

    // Wait a bit for any async operations
    await new Promise(resolve => setTimeout(resolve, 100))

    // precomputeTypingChargeCache should NOT be called on submit path (P0 change)
    expect(api.precomputeTypingChargeCache).not.toHaveBeenCalled()
  })

  it('does not expose Method 2 periodic override', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <BatchJobBinderCell />
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('Batch Job / Binder Cell')).toBeInTheDocument()
    })

    expect(screen.getByLabelText('E_intra Method Override')).not.toHaveTextContent(
      'Periodic PPPM',
    )
  })

  it('selects the settings default E_intra method initially', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <BatchJobBinderCell />
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('Batch Job / Binder Cell')).toBeInTheDocument()
    })

    expect(screen.getByLabelText('E_intra Method Override')).toHaveValue(
      'single_molecule_vacuum_adaptive_cutoff',
    )
  })

})
