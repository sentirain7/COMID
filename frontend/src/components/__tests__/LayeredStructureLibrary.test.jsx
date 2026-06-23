import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LayeredStructureLibrary from '../LayeredStructureLibrary'

let mockCedProfileData = {
  exp_id: 'EXP_LAYER_001',
  metric_name: 'cohesive_energy_density_profile',
  namespace: 'layer',
  columns: {
    layer_index: [0, 1],
    layer_label: ['layer_0', 'layer_1'],
    ced_MJ_m3: [123.4, 98.7],
    volume_A3: [400.0, 600.0],
  },
  metadata: {
    e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
  },
}

vi.mock('../MoleculeViewer', () => ({
  MoleculeViewer: () => <div data-testid="mock-viewer" />,
}))

vi.mock('../ThermoChart', () => ({
  default: () => <div data-testid="mock-thermo" />,
}))

vi.mock('../Charts/StressStrainChart', () => ({
  default: () => <div data-testid="mock-stress" />,
}))

vi.mock('../../hooks/useApiLayeredStructures', async () => {
  const actual = await vi.importActual('../../hooks/useApiLayeredStructures')
  return {
    ...actual,
    useLayeredExperiments: () => ({
      data: {
        items: [
          {
            exp_id: 'EXP_LAYER_001',
            name: 'Layered A',
            status: 'completed',
            temperature_K: 298,
            layer_count: 2,
            layers: [
              { layer_index: 0, label: 'binder', source_type: 'binder_cell' },
              { layer_index: 1, label: 'interface', source_type: 'interface_molecule_cell' },
            ],
            tensile_strength: 8.1,
          },
        ],
      },
      loading: false,
      error: null,
      execute: vi.fn(),
    }),
    useStressStrainCurve: () => ({
      data: {
        strain: [0, 0.1, 0.2],
        stress_MPa: [0, 1, 0.5],
        peak_index: 1,
      },
      loading: false,
      error: null,
    }),
  }
})

vi.mock('../../hooks/useApiExperiments', async () => {
  const actual = await vi.importActual('../../hooks/useApiExperiments')
  return {
    ...actual,
    useBatchDeleteExperiments: () => ({
      mutateAsync: vi.fn(),
      isPending: false,
    }),
  }
})

vi.mock('../../hooks/useApi', async () => {
  const actual = await vi.importActual('../../hooks/useApi')
  return {
    ...actual,
    useArrayMetricData: () => ({
      data: mockCedProfileData,
      loading: false,
      error: null,
    }),
  }
})

function renderWithQuery(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('LayeredStructureLibrary', () => {
  beforeEach(() => {
    mockCedProfileData = {
      exp_id: 'EXP_LAYER_001',
      metric_name: 'cohesive_energy_density_profile',
      namespace: 'layer',
      columns: {
        layer_index: [0, 1],
        layer_label: ['layer_0', 'layer_1'],
        ced_MJ_m3: [123.4, 98.7],
        volume_A3: [400.0, 600.0],
      },
      metadata: {
        e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
      },
    }
  })

  it('renders the layered CED profile table with stored method badge', async () => {
    renderWithQuery(<LayeredStructureLibrary />)

    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scan Database' })).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('Layered CED Profile')).toBeInTheDocument()
    })

    expect(screen.getByText('layer_0')).toBeInTheDocument()
    expect(screen.getByText('layer_1')).toBeInTheDocument()
    expect(screen.getByText('123.40')).toBeInTheDocument()
    expect(screen.getByText('98.70')).toBeInTheDocument()
    expect(screen.getByText('Vacuum Adaptive')).toBeInTheDocument()
  })

  it('shows the stored historical method label without relabeling to submission defaults', async () => {
    mockCedProfileData = {
      exp_id: 'EXP_LAYER_001',
      metric_name: 'cohesive_energy_density_profile',
      namespace: 'layer',
      columns: {
        layer_index: [0],
        layer_label: ['layer_0'],
        ced_MJ_m3: [88.1],
        volume_A3: [500.0],
      },
      metadata: {
        e_intra_method: 'single_molecule_periodic',
      },
    }

    renderWithQuery(<LayeredStructureLibrary />)

    await waitFor(() => {
      expect(screen.getByText('Layered CED Profile')).toBeInTheDocument()
    })

    expect(screen.getByText('Periodic PPPM')).toBeInTheDocument()
  })
})
