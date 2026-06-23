import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import BatchSingleMoleculeScreen from '../BatchSingleMoleculeScreen'

// Mock data — asphalt_binder molecules with different submittable states
const createMockMolecules = () => [
  {
    mol_id: 'U-AS-Thio-0293',
    category: 'asphaltene',
    molecular_weight: 356.0,
    atom_count: 42,
    structure_file: 'asphalt_binder/U-AS-Thio-0293.mol',
    aging_state: 'non_aging',
    base_id: 'Thiophenol',
    source: 'asphalt_binder',
    ff_hint: 'gaff2',
    ff_display_label: 'GAFF2',
    route: 'organic_curated_artifact',
    is_submittable: true,
  },
  {
    mol_id: 'U-SA-Squalane',
    category: 'saturate',
    molecular_weight: 422.8,
    atom_count: 62,
    structure_file: 'asphalt_binder/U-SA-Squalane.mol',
    aging_state: 'non_aging',
    base_id: 'Squalane',
    source: 'asphalt_binder',
    ff_hint: 'gaff2',
    ff_display_label: 'GAFF2',
    route: 'organic_curated_artifact',
    is_submittable: true,
  },
  {
    mol_id: 'TestAdditive',
    category: null,
    molecular_weight: 200.0,
    atom_count: 20,
    structure_file: 'additives/TestAdditive.mol',
    aging_state: null,
    base_id: 'TestAdditive',
    source: 'additives',
    ff_hint: 'gaff2',
    ff_display_label: 'GAFF2',
    route: 'organic_curated_artifact',
    is_submittable: true,
  },
]

// Mutable reference for molecule data — tests can modify this
let currentMolecules = createMockMolecules()
const mockUseMolecules = vi.fn(() => ({
  molecules: currentMolecules,
  loading: false,
  isFetching: false,
  error: null,
  refetch: vi.fn(),
}))

// Mock submit mutation with spy
const mockMutateAsync = vi.fn(async () => ({ submitted: 1 }))

vi.mock('../../hooks/useMolecules', () => ({
  useMolecules: (args) => mockUseMolecules(args),
}))

vi.mock('../../hooks/useApiExperiments', () => ({
  useExperimentDefaults: () => ({ data: { temperatures_k: [293, 298] } }),
  useSubmitSingleMoleculeBatch: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}))

vi.mock('../../hooks/useApi', () => ({
  useSettings: () => ({
    settings: {
      default_e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
    },
    loading: false,
    error: null,
    update: vi.fn(),
  }),
}))

vi.mock('../../hooks/useEIntraLive', () => ({
  useEIntraLive: vi.fn(),
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    precomputeTypingChargeCache: vi.fn(),
  }
})

// Reset mock molecules and spy before each test
beforeEach(() => {
  currentMolecules = createMockMolecules()
  mockMutateAsync.mockClear()
  mockUseMolecules.mockClear()
})

describe('BatchSingleMoleculeScreen — Fail-Closed Gating', () => {
  const createQueryClient = () =>
    new QueryClient({ defaultOptions: { queries: { retry: false } } })

  const renderScreen = () => {
    const queryClient = createQueryClient()
    const view = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BatchSingleMoleculeScreen />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    return {
      ...view,
      rerender: () =>
        view.rerender(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <BatchSingleMoleculeScreen />
            </MemoryRouter>
          </QueryClientProvider>,
        ),
    }
  }

  it('renders PageHeader when molecules are loaded', async () => {
    renderScreen()
    expect(screen.getByText('Batch Job / Single Molecule')).toBeInTheDocument()
  })

  describe('stale/refetch scenarios', () => {
    it('disables submit when selected molecule becomes blocked (is_submittable=false) after data change', () => {
      const view = renderScreen()

      // 1. Select submittable molecule
      const chip = screen.getByRole('button', { name: /Thiophenol/i })
      fireEvent.click(chip)

      // Submit should be enabled initially
      const submitButton = screen.getByRole('button', { name: /Submit/i })
      expect(submitButton).not.toBeDisabled()

      // 2. Simulate refetch — molecule becomes blocked
      currentMolecules = currentMolecules.map((m) =>
        m.mol_id === 'U-AS-Thio-0293'
          ? { ...m, is_submittable: false, blocked_reason: 'Artifact not found' }
          : m,
      )

      // 3. Trigger rerender (simulates useMolecules returning new data)
      view.rerender()

      // 4. Submit should now be disabled
      expect(screen.getByRole('button', { name: /Submit/i })).toBeDisabled()

      // 5. Inline hint should be visible (organic route → artifact message)
      expect(screen.getByText(/require.*artifacts before submission/i)).toBeInTheDocument()
      // 6. /molecules management link should be rendered (v00.99.66) and
      //    carry the first blocked mol_id so /molecules auto-selects it.
      const manageLink = screen.getByRole('link', { name: /Manage FF artifacts/i })
      expect(manageLink).toHaveAttribute(
        'href',
        '/molecules?mol_id=U-AS-Thio-0293',
      )
    })

    it('disables submit when selected molecule disappears from data', () => {
      const view = renderScreen()

      // 1. Select submittable molecule
      fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))
      expect(screen.getByRole('button', { name: /Submit/i })).not.toBeDisabled()

      // 2. Simulate refetch — molecule completely removed from data
      currentMolecules = currentMolecules.filter((m) => m.mol_id !== 'U-AS-Thio-0293')

      // 3. Trigger rerender
      view.rerender()

      // 4. Submit should be disabled (fail-closed: disappeared = blocked)
      expect(screen.getByRole('button', { name: /Submit/i })).toBeDisabled()

      // 5. Generic hint should be visible (not allOrganic since mol is null)
      expect(screen.getByText(/currently not submittable/i)).toBeInTheDocument()
    })

    it('disables submit when hidden-tab molecule becomes blocked', () => {
      const view = renderScreen()

      // 1. Select molecule from asphalt_binder tab
      fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))
      expect(screen.getByRole('button', { name: /Submit/i })).not.toBeDisabled()

      // 2. Switch to additives tab (hides original selection from view)
      const additivesTab = screen.getByRole('button', { name: /additives/i })
      fireEvent.click(additivesTab)

      // 3. Simulate refetch — original molecule becomes blocked
      currentMolecules = currentMolecules.map((m) =>
        m.mol_id === 'U-AS-Thio-0293' ? { ...m, is_submittable: false } : m,
      )

      // 4. Trigger rerender
      view.rerender()

      // 5. Submit should be disabled (hidden-tab selection still tracked)
      expect(screen.getByRole('button', { name: /Submit/i })).toBeDisabled()

      // 6. Inline hint should be visible
      expect(screen.getByText(/require.*artifacts before submission/i)).toBeInTheDocument()
    })

    it('does not call mutateAsync when submit clicked on blocked selection', async () => {
      const view = renderScreen()

      // Select molecule
      fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))

      // Make it blocked
      currentMolecules = currentMolecules.map((m) =>
        m.mol_id === 'U-AS-Thio-0293' ? { ...m, is_submittable: false } : m,
      )
      view.rerender()

      // Try to click submit (should be disabled, but test the guard too)
      const submitButton = screen.getByRole('button', { name: /Submit/i })
      fireEvent.click(submitButton)

      // mutateAsync should NOT have been called
      expect(mockMutateAsync).not.toHaveBeenCalled()
    })
  })

  describe('selection behavior', () => {
    it('maintains selection when molecule becomes blocked (so the /molecules manage link stays actionable)', () => {
      const view = renderScreen()

      // Select molecule
      fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))

      // Make it blocked
      currentMolecules = currentMolecules.map((m) =>
        m.mol_id === 'U-AS-Thio-0293' ? { ...m, is_submittable: false } : m,
      )
      view.rerender()

      // Selection should be maintained (inline hint references selected molecule)
      expect(screen.getByText(/1 selected molecule/i)).toBeInTheDocument()
    })

    it('enables submit when only submittable molecules are selected', () => {
      renderScreen()

      // Select submittable molecule
      fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))

      // Submit should be enabled
      expect(screen.getByRole('button', { name: /Submit/i })).not.toBeDisabled()

      // No inline hint
      expect(screen.queryByText(/require.*artifacts before submission/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/currently not submittable/i)).not.toBeInTheDocument()
    })
  })

  describe('artifact warning UX (v00.99.66)', () => {
    it('keeps submit enabled without surfacing artifact-warning diagnostics', () => {
      currentMolecules = currentMolecules.map((m) =>
        m.mol_id === 'U-AS-Thio-0293'
          ? {
              ...m,
              is_submittable: true,
              blocked_reason: null,
              artifact_warning: "Artifact not found for 'U-AS-Thio-0293'.",
              ff_display_label: 'GAFF2',
            }
          : m,
      )
      renderScreen()

      const chip = screen.getByRole('button', { name: /Thiophenol/i })
      expect(chip).not.toBeDisabled()
      expect(chip.getAttribute('title')).not.toMatch(/generate|artifact/i)

      fireEvent.click(chip)
      expect(screen.getByRole('button', { name: /Submit/i })).not.toBeDisabled()
      expect(screen.queryByText(/will generate|auto-generate|submit: bulk_ff_gaff2/i)).not.toBeInTheDocument()

      // No blocked-style inline hint should appear.
      expect(screen.queryByText(/require.*artifacts before submission/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/currently not submittable/i)).not.toBeInTheDocument()
    })
  })

  it('submits the default E_intra method for batch requests', async () => {
    renderScreen()

    fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))
    fireEvent.click(screen.getByRole('button', { name: /Submit/i }))

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalled()
    })

    expect(mockMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
      }),
    )
  })

  it('does not expose Method 2 periodic override for batch requests', async () => {
    renderScreen()

    expect(screen.getByLabelText('E_intra Method Override')).not.toHaveTextContent(
      'Periodic PPPM',
    )
  })

  it('selects the settings default E_intra method initially for batch requests', async () => {
    renderScreen()

    expect(screen.getByLabelText('E_intra Method Override')).toHaveValue(
      'single_molecule_vacuum_adaptive_cutoff',
    )
  })

  it('queries molecule coverage with the active submission E_intra method', () => {
    renderScreen()

    expect(mockUseMolecules).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 5000,
        eIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
      }),
    )
  })
})
