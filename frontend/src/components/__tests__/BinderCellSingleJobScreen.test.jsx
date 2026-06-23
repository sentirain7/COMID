import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BinderCellSingleJobScreen from '../BinderCellSingleJobScreen'
import * as api from '../../api/client'

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

vi.mock('../../api/client', () => ({
  submitMoleculeExperiment: vi.fn(),
  getBinderComposition: vi.fn(async () => ({
    molecules: [
      { mol_id: 'SA-Squalane', count: 10, sara_type: 'saturate', atom_count: 62 },
    ],
    total_molecules: 10,
    estimated_atoms: 620,
    sara_fractions: { saturate: 0.5, aromatic: 0.2, resin: 0.2, asphaltene: 0.1 },
  })),
  listBinderTypes: vi.fn(async () => ({
    binder_types: [{ name: 'AAA1', description: 'default', sara_fractions: {} }],
  })),
  listAdditives: vi.fn(async () => ({ additives: [] })),
  listMolecules: vi.fn(async () => ({ molecules: [] })),
  getDefaultStages: vi.fn(async () => ({
    stages: [
      { name: 'minimize', type: 'minimize', editable: true, duration_ps: null, duration_steps: 1000 },
      { name: 'nvt_equilibration', type: 'nvt', editable: true, duration_ps: 300, duration_steps: null },
      { name: 'npt_production', type: 'npt', editable: true, duration_ps: 2000, duration_steps: null },
    ],
  })),
  previewMoleculeComposition: vi.fn(async () => ({
    sara_fractions: { resin: 0.6, aromatic: 0.1, saturate: 0.2, asphaltene: 0.1 },
    estimated_atoms: 620,
    total_molecules: 10,
  })),
}))

describe('BinderCellSingleJobScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.submitMoleculeExperiment.mockResolvedValue({})
    api.getBinderComposition.mockResolvedValue({
      molecules: [
        { mol_id: 'SA-Squalane', count: 10, sara_type: 'saturate', atom_count: 62 },
      ],
      total_molecules: 10,
      estimated_atoms: 620,
      sara_fractions: { saturate: 0.5, aromatic: 0.2, resin: 0.2, asphaltene: 0.1 },
    })
    api.listBinderTypes.mockResolvedValue({
      binder_types: [{ name: 'AAA1', description: 'default', sara_fractions: {} }],
    })
    api.listAdditives.mockResolvedValue({ additives: [] })
    api.listMolecules.mockResolvedValue({ molecules: [] })
    api.getDefaultStages.mockResolvedValue({
      stages: [
        { name: 'minimize', type: 'minimize', editable: true, duration_ps: null, duration_steps: 1000 },
        { name: 'nvt_equilibration', type: 'nvt', editable: true, duration_ps: 300, duration_steps: null },
        { name: 'npt_production', type: 'npt', editable: true, duration_ps: 2000, duration_steps: null },
      ],
    })
    api.previewMoleculeComposition.mockResolvedValue({
      sara_fractions: { resin: 0.6, aromatic: 0.1, saturate: 0.2, asphaltene: 0.1 },
      estimated_atoms: 620,
      total_molecules: 10,
      ff_blocked_items: [],
      ff_warning_items: [],
    })
  })

  it('renders form shell', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })
  })

  it('falls back to default binder types when API returns empty', async () => {
    api.listBinderTypes.mockResolvedValueOnce({ binder_types: [] })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'AAA1' })).toBeInTheDocument()
    })
  })

  it('clears stale SARA summary and previews custom composition', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    const customButton = screen.getByRole('button', { name: /custom/i })
    customButton.click()

    await waitFor(() => {
      expect(api.previewMoleculeComposition).toHaveBeenCalled()
    })

    expect(screen.queryByText('50.0%')).not.toBeInTheDocument()
    expect(screen.queryByText('60.0%')).not.toBeInTheDocument()
  })

  it('applies the last temperature interaction (preset vs input) on submit', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    const preset333 = screen.getByRole('button', { name: '333K' })
    fireEvent.click(preset333)

    const temperatureInput = screen.getByRole('spinbutton', { name: 'Temperature (K)' })
    fireEvent.change(temperatureInput, { target: { value: '321' } })

    const submitButton = screen.getByRole('button', { name: /Submit/i })
    fireEvent.click(submitButton)

    await waitFor(() => {
      expect(api.submitMoleculeExperiment).toHaveBeenCalled()
    })

    const payload = api.submitMoleculeExperiment.mock.calls.at(-1)?.[0]
    expect(payload.temperature_K).toBe(321)
    expect(payload.e_intra_method).toBe('single_molecule_vacuum_adaptive_cutoff')
  })

  it('toggles preset temperature off when clicked twice', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    const preset333 = screen.getByRole('button', { name: '333K' })
    fireEvent.click(preset333)
    await waitFor(() => {
      expect(preset333).toHaveAttribute('aria-pressed', 'true')
    })

    fireEvent.click(preset333)
    await waitFor(() => {
      expect(preset333).toHaveAttribute('aria-pressed', 'false')
    })

    const temperatureInput = screen.getByRole('spinbutton', { name: 'Temperature (K)' })
    expect(temperatureInput).toHaveValue(null)
  })

  it('ignores ff_warning_items in submit UI without gating submit', async () => {
    api.previewMoleculeComposition.mockResolvedValueOnce({
      sara_fractions: { resin: 0.6, aromatic: 0.1, saturate: 0.2, asphaltene: 0.1 },
      estimated_atoms: 620,
      total_molecules: 10,
      ff_blocked_items: [],
      ff_warning_items: [
        {
          item_id: 'SA-Squalane',
          item_kind: 'molecule',
          route: 'organic_curated_artifact',
          status: 'warn',
          message: "Artifact not found for 'SA-Squalane'.",
        },
      ],
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(api.previewMoleculeComposition).toHaveBeenCalled()
    })
    expect(screen.queryByTestId('ff-warning-banner')).not.toBeInTheDocument()
    expect(screen.queryByText(/auto-generate artifact|First build will/i)).not.toBeInTheDocument()
    // Warning must not gate submit.
    expect(screen.getByRole('button', { name: /Submit/i })).not.toBeDisabled()
  })

  it('blocks submit when ff_blocked_items are present', async () => {
    api.previewMoleculeComposition.mockResolvedValueOnce({
      sara_fractions: { resin: 0.6, aromatic: 0.1, saturate: 0.2, asphaltene: 0.1 },
      estimated_atoms: 620,
      total_molecules: 10,
      ff_blocked_items: [
        {
          item_id: 'H2SO4',
          item_kind: 'additive',
          route: 'ionic_profile',
          status: 'blocked',
          message: 'Ionic profile not yet available.',
        },
      ],
      ff_warning_items: [],
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(api.previewMoleculeComposition).toHaveBeenCalled()
      expect(screen.getByText(/1 species require FF artifacts before submission/i)).toBeInTheDocument()
    })
    const manageLink = screen.getByRole('link', { name: /Manage FF artifacts/i })
    expect(manageLink).toHaveAttribute('href', '/molecules?mol_id=H2SO4')
    expect(screen.queryByText(/Ionic profile not yet available/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Submit/i })).toBeDisabled()
  })

  it('applies boundary and seed to submission payload', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'p p p' }))
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Seed' }), {
      target: { value: '123' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Submit/i }))

    await waitFor(() => {
      expect(api.submitMoleculeExperiment).toHaveBeenCalled()
    })

    const payload = api.submitMoleculeExperiment.mock.calls.at(-1)?.[0]
    expect(payload.study_type).toBe('bulk')
    expect(payload.seed).toBe(123)
  })

  it('does not expose Method 2 periodic override', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    expect(screen.getByLabelText('E_intra Method Override')).not.toHaveTextContent(
      'Periodic PPPM',
    )
  })

  it('selects the settings default E_intra method initially', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BinderCellSingleJobScreen />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Binder Cell/i })).toBeInTheDocument()
    })

    expect(screen.getByLabelText('E_intra Method Override')).toHaveValue(
      'single_molecule_vacuum_adaptive_cutoff',
    )
  })
})
