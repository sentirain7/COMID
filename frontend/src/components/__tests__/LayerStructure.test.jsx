import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import LayerStructure from '../LayerStructure'

const mockApi = vi.hoisted(() => ({
  submitMutateAsync: vi.fn(async () => ({ exp_id: 'EXP_LYR_0001', job_id: 'job-layer-1' })),
  previewMutateAsync: vi.fn(async () => ({
    xyz: '',
    box_size: [40, 40, 30],
    n_atoms: 0,
    n_bonds: 0,
    bonds: [],
    layer_boundaries_z: [0, 10, 20, 30],
    checks: [],
  })),
}))

vi.mock('../ProtocolTimeline', () => ({
  default: () => <div data-testid="protocol-timeline" />,
}))

vi.mock('../ProtocolStagesPanel', () => ({
  default: () => <div data-testid="protocol-stages" />,
}))

vi.mock('../../hooks/useProtocolStages', () => ({
  default: () => ({
    selectedStages: {
      minimize: true,
      nvt_equilibration: true,
      npt_production: true,
    },
    stageConfig: {
      minimize: { name: 'Energy Minimization', type: 'minimize' },
      nvt_equilibration: { name: 'NVT', type: 'nvt' },
      npt_production: { name: 'NPT', type: 'npt' },
    },
    stageDurations: {
      minimize: { steps: 1000, ps: 1 },
      nvt_equilibration: { steps: null, ps: 300 },
      npt_production: { steps: null, ps: 2000 },
    },
    loadingStages: false,
    computedRunTier: 'screening',
    toggleStage: vi.fn(),
    handleDurationChange: vi.fn(),
    resetDurationToDefault: vi.fn(),
    isDurationModified: () => false,
    buildStageOverrides: () => [],
    timelineStageConfig: {
      minimize: { name: 'Energy Minimization', type: 'minimize', duration_ps: 1 },
      nvt_equilibration: { name: 'NVT', type: 'nvt', duration_ps: 300 },
      npt_production: { name: 'NPT', type: 'npt', duration_ps: 2000 },
    },
    addViscosityTemp: vi.fn(),
    removeViscosityTemp: vi.fn(),
    updateViscosityTemp: vi.fn(),
  }),
}))

vi.mock('../../hooks/useApi', () => ({
  useLayerSources: (sourceType) => {
    if (sourceType === 'binder_cell') {
      return {
        data: {
          items: [{ source_id: 'binder_001', name: 'Binder Source', source_type: 'binder_cell' }],
        },
      }
    }
    if (sourceType === 'interface_molecule_cell') {
      return {
        data: {
          items: [{ source_id: 'interface_001', name: 'Interface Molecule Source', source_type: 'interface_molecule_cell' }],
        },
      }
    }
    return {
      data: {
        items: [{ source_id: 'crystal_001', name: 'Crystal Source', source_type: 'crystal_structure' }],
      },
    }
  },
  useLayeredStructurePreview: () => ({
    mutateAsync: mockApi.previewMutateAsync,
    isPending: false,
    data: null,
    error: null,
  }),
  useLayeredStructureSubmit: () => ({
    mutateAsync: mockApi.submitMutateAsync,
    isPending: false,
    error: null,
  }),
  useSettings: () => ({
    settings: {
      default_e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
    },
    loading: false,
    error: null,
    update: vi.fn(),
  }),
}))

describe('LayerStructure', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('applies last temperature interaction (preset -> input) to submit payload', async () => {
    render(
      <MemoryRouter initialEntries={['/single-job/layered-structure']}>
        <LayerStructure />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Layered Structure/i })).toBeInTheDocument()
    })

    const sourceSelects = screen
      .getAllByRole('combobox')
      .filter((element) =>
        Array.from(element.options || []).some((option) => option.textContent?.includes('Select source...'))
      )

    expect(sourceSelects).toHaveLength(3)
    fireEvent.change(sourceSelects[0], { target: { value: 'binder_001' } })
    fireEvent.change(sourceSelects[1], { target: { value: 'interface_001' } })
    fireEvent.change(sourceSelects[2], { target: { value: 'crystal_001' } })

    fireEvent.click(screen.getByRole('button', { name: '333K' }))
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature (K)' }), {
      target: { value: '321' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))

    await waitFor(() => {
      expect(mockApi.submitMutateAsync).toHaveBeenCalled()
    })

    const payload = mockApi.submitMutateAsync.mock.calls.at(-1)?.[0]
    expect(payload.temperature_K).toBe(321)
    expect(payload.e_intra_method).toBe('single_molecule_vacuum_adaptive_cutoff')
  })

  it('does not expose Method 2 periodic override', async () => {
    render(
      <MemoryRouter initialEntries={['/single-job/layered-structure']}>
        <LayerStructure />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Layered Structure/i })).toBeInTheDocument()
    })

    const sourceSelects = screen
      .getAllByRole('combobox')
      .filter((element) =>
        Array.from(element.options || []).some((option) => option.textContent?.includes('Select source...'))
      )

    fireEvent.change(sourceSelects[0], { target: { value: 'binder_001' } })
    fireEvent.change(sourceSelects[1], { target: { value: 'interface_001' } })
    fireEvent.change(sourceSelects[2], { target: { value: 'crystal_001' } })
    expect(screen.getByLabelText('E_intra Method Override')).not.toHaveTextContent(
      'Periodic PPPM',
    )
  })

  it('selects the settings default E_intra method initially', async () => {
    render(
      <MemoryRouter>
        <LayerStructure />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Layered Structure/i })).toBeInTheDocument()
    })

    expect(screen.getByLabelText('E_intra Method Override')).toHaveValue(
      'single_molecule_vacuum_adaptive_cutoff',
    )
  })
})
