import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import SingleMoleculeScreen from '../SingleMoleculeScreen'

// Mutable reference for molecule data — tests can modify this
let currentMolecules = [
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
]
const mockUseMolecules = vi.fn(() => ({
  molecules: currentMolecules,
  loading: false,
  isFetching: false,
  error: null,
  refetch: vi.fn(),
}))

const mockMutateAsync = vi.fn(async () => ({ submitted: 1 }))

vi.mock('../../hooks/useMolecules', () => ({
  useMolecules: (args) => mockUseMolecules(args),
}))

vi.mock('../../hooks/useApiExperiments', () => ({
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
  currentMolecules = [
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
  ]
  mockMutateAsync.mockClear()
  mockUseMolecules.mockClear()
})

describe('SingleMoleculeScreen', () => {
  const createQueryClient = () =>
    new QueryClient({ defaultOptions: { queries: { retry: false } } })

  const renderScreen = () => {
    const queryClient = createQueryClient()
    const view = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SingleMoleculeScreen />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    return {
      ...view,
      rerender: () =>
        view.rerender(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <SingleMoleculeScreen />
            </MemoryRouter>
          </QueryClientProvider>,
        ),
    }
  }

  it('renders PageHeader when molecules are loaded', async () => {
    renderScreen()
    await waitFor(() => {
      expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
    })
  })

  it('keeps screen shell when molecules are present (no spinner takeover)', async () => {
    renderScreen()
    await waitFor(() => {
      // Loading spinner should NOT be visible when molecules are loaded
      expect(screen.queryByText('Loading molecules...')).not.toBeInTheDocument()
      // Page shell should be present
      expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
    })
  })

  describe('stale/refetch scenarios', () => {
    it('disables submit when selected molecule disappears from data', async () => {
      const view = renderScreen()

      await waitFor(() => {
        expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
      })

      // 1. Select molecule
      const chip = screen.getByRole('button', { name: /Thiophenol/i })
      fireEvent.click(chip)

      // Submit should be enabled initially
      const submitButton = screen.getByRole('button', { name: /Submit/i })
      expect(submitButton).not.toBeDisabled()

      // 2. Simulate refetch — molecule completely removed from data
      currentMolecules = []

      // 3. Trigger rerender
      view.rerender()

      // 4. Submit should be disabled (fail-closed: selectedMolecule is null)
      expect(screen.getByRole('button', { name: /Submit/i })).toBeDisabled()
    })

    it('does not call mutateAsync when molecule has disappeared', async () => {
      const view = renderScreen()

      await waitFor(() => {
        expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
      })

      // Select molecule
      fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))

      // Remove molecule from data
      currentMolecules = []
      view.rerender()

      // Try to click submit
      fireEvent.click(screen.getByRole('button', { name: /Submit/i }))

      // mutateAsync should NOT have been called
      expect(mockMutateAsync).not.toHaveBeenCalled()
    })

    it('disables submit when selected molecule becomes blocked', async () => {
      const view = renderScreen()

      await waitFor(() => {
        expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
      })

      // Select molecule
      fireEvent.click(screen.getByRole('button', { name: /Thiophenol/i }))
      expect(screen.getByRole('button', { name: /Submit/i })).not.toBeDisabled()

      // Make it blocked
      currentMolecules = currentMolecules.map((m) => ({
        ...m,
        is_submittable: false,
      }))
      view.rerender()

      // Submit should be disabled
      expect(screen.getByRole('button', { name: /Submit/i })).toBeDisabled()
      // /molecules management link surfaces for artifact generation
      // (v00.99.66). The href carries mol_id so /molecules auto-selects
      // the blocked molecule on arrival.
      const manageLink = screen.getByRole('link', { name: /Manage FF artifacts/i })
      expect(manageLink).toHaveAttribute(
        'href',
        '/molecules?mol_id=U-AS-Thio-0293',
      )
    })
  })

  describe('artifact warning UX (v00.99.66)', () => {
    it('keeps chip selectable without surfacing artifact-warning diagnostics', async () => {
      currentMolecules = [
        {
          ...currentMolecules[0],
          is_submittable: true,
          blocked_reason: null,
          artifact_warning: "Artifact not found for 'Thiophenol'.",
          ff_display_label: 'GAFF2',
        },
      ]
      renderScreen()

      await waitFor(() => {
        expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
      })

      const chip = screen.getByRole('button', { name: /Thiophenol/i })
      // Must not be disabled — warning is informational, not a block.
      expect(chip).not.toBeDisabled()
      expect(chip.getAttribute('title')).not.toMatch(/generate|artifact/i)
      expect(screen.queryByText(/will generate|auto-generate|submit: bulk_ff_gaff2/i)).not.toBeInTheDocument()

      fireEvent.click(chip)
      const submitButton = screen.getByRole('button', { name: /Submit/i })
      expect(submitButton).not.toBeDisabled()
    })
  })

  it('submits the default E_intra method when no override is selected', async () => {
    renderScreen()

    await waitFor(() => {
      expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
    })

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

  it('does not expose Method 2 periodic override', async () => {
    renderScreen()

    await waitFor(() => {
      expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
    })

    expect(screen.getByLabelText('E_intra Method Override')).not.toHaveTextContent(
      'Periodic PPPM',
    )
  })

  it('selects the settings default E_intra method initially', async () => {
    renderScreen()

    await waitFor(() => {
      expect(screen.getByText('Single Job / Single Molecule')).toBeInTheDocument()
    })

    expect(screen.getByLabelText('E_intra Method Override')).toHaveValue(
      'single_molecule_vacuum_adaptive_cutoff',
    )
  })

  it('queries molecule coverage with the active submission E_intra method', async () => {
    renderScreen()

    await waitFor(() => {
      expect(mockUseMolecules).toHaveBeenCalledWith(
        expect.objectContaining({
          limit: 5000,
          eIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
        }),
      )
    })
  })
})
