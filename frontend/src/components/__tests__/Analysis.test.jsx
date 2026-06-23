import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import Analysis from '../Analysis'

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }) => <div data-testid="mock-canvas">{children}</div>,
}))

vi.mock('../../hooks/useApi', () => ({
  useAnalysisEmbedding: () => ({
    data: [],
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useBinderCellXYSummary: () => ({
    data: {
      group_by: 'binder',
      total_samples: 3,
      overview: {
        sample_count: 3,
        avg_density: 1.01,
        avg_total_energy: -980.0,
        avg_potential_energy: -1180.0,
        avg_kinetic_energy: 200.0,
      },
      items: [
        {
          group_key: 'A1',
          group_label: 'A1',
          sample_count: 2,
          avg_lx: 42.0,
          avg_ly: 44.0,
          avg_xy: 43.0,
        },
        {
          group_key: 'K1',
          group_label: 'K1',
          sample_count: 1,
          avg_lx: 50.0,
          avg_ly: 48.0,
          avg_xy: 49.0,
        },
      ],
    },
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useScatter3D: () => ({
    data: [],
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useLayeredAnalysis3D: () => ({
    data: { total: 0, items: [], available_layer_types: [], available_crystal_materials: [], available_aging_states: [], available_binder_types: [], temp_range: null },
    loading: false,
    error: null,
  }),
  useExplorerCatalog: () => ({ data: [], loading: false, error: null }),
  useExplorerData: () => ({ data: null, loading: false, error: null }),
  useExplorerAggregate: () => ({ data: null, loading: false, error: null }),
}))

vi.mock('../Analysis/BinderPropertyViews', () => ({
  __esModule: true,
  default: () => <div data-testid="binder-property-views" />,
  ScatterScene: () => <div data-testid="scatter-scene" />,
}))

vi.mock('../Analysis/StateGraph2D', () => ({
  __esModule: true,
  default: () => <div data-testid="state-graph-2d" />,
}))

vi.mock('../Analysis/StateGraph3D', () => ({
  __esModule: true,
  default: () => <div data-testid="state-graph-3d" />,
}))

vi.mock('../Charts/TemperaturePropertyChart', () => ({
  __esModule: true,
  default: () => <div data-testid="temperature-property-chart" />,
}))

vi.mock('../Charts/AdditiveImpactChart', () => ({
  __esModule: true,
  default: () => <div data-testid="additive-impact-chart" />,
}))

vi.mock('../Analysis/ScatterPrimitives', () => ({
  AxisLines: () => null,
  ScatterPoint: () => null,
  ScatterCanvas: ({ children }) => <>{children}</>,
  CategoryTickLabels: () => null,
}))

function renderWithQuery(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('Analysis', () => {
  it('renders tabs and default Bulk Properties tab', async () => {
    renderWithQuery(<Analysis />)

    // Tab buttons should be visible
    expect(screen.getByRole('tab', { name: 'Bulk Properties' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Layered Structures' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'GHG & Sustainability' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Composition Transitions' })).toBeInTheDocument()

    // Default tab (Bulk Properties) shows 3D Property Embedding
    expect(screen.getByText('3D Property Embedding')).toBeInTheDocument()
  })

  it('shows composition state transitions on Composition Transitions tab', async () => {
    renderWithQuery(<Analysis />)

    // Switch to Composition Transitions tab
    await userEvent.click(screen.getByRole('tab', { name: 'Composition Transitions' }))

    await waitFor(() => {
      expect(screen.getByText('Composition State Transitions')).toBeInTheDocument()
    })
  })

  it('shows Layered Structures tab content', async () => {
    renderWithQuery(<Analysis />)

    await userEvent.click(screen.getByRole('tab', { name: 'Layered Structures' }))

    await waitFor(() => {
      expect(screen.getByText('Layered Structure 3D Analysis')).toBeInTheDocument()
    })
  })
})
