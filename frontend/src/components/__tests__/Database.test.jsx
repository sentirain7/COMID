import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Database from '../Database'

vi.mock('../database/ExperimentDetail', () => ({
  default: () => <div data-testid="mock-experiment-detail" />,
}))

vi.mock('../MoleculeViewer', () => ({
  default: () => <div data-testid="mock-molecule-viewer" />,
  MoleculeViewer: () => <div data-testid="mock-molecule-viewer" />,
  SimpleViewer: () => <div data-testid="mock-simple-viewer" />,
}))

const mockApi = vi.hoisted(() => ({
  deleteMutateAsync: vi.fn(),
}))

const mockMutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, data: null, error: null })

vi.mock('../../hooks/useApi', () => ({
  useExperiments: () => ({
    data: {
      experiments: [
        {
          exp_id: 'A1_X2_NA_SBS_298K_abc123',
          status: 'completed',
          binder_code: 'A1',
          binder_type: 'AAA1',
          structure_size: 'X2',
          aging_code: 'NA',
          aging_state: 'non_aging',
          additive_label: 'SBS',
          box_lx: 42,
          box_ly: 44,
          box_lz: 25,
          created_at: '2026-03-17T00:00:00Z',
          completed_at: '2026-03-17T01:00:00Z',
        },
      ],
    },
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useExperimentDetail: () => ({
    data: {
      exp_id: 'A1_X2_NA_SBS_298K_abc123',
      status: 'completed',
      binder_code: 'A1',
      binder_type: 'AAA1',
      structure_size: 'X2',
      aging_code: 'NA',
      aging_state: 'non_aging',
      additive_label: 'SBS',
      actual_atoms: 5000,
      box_lx: 42,
      box_ly: 44,
      box_lz: 25,
      data_file_path: '/tmp/data.lammps',
      force_field_type: 'GAFF2',
      temperature_k: 298,
      seed: 42,
      created_at: '2026-03-17T00:00:00Z',
      completed_at: '2026-03-17T01:00:00Z',
      mol_counts: null,
      mol_details: null,
      total_mass: null,
    },
    loading: false,
    error: null,
  }),
  useExperimentMetrics: () => ({ data: null, loading: false, error: null }),
  useExperimentFilterOptions: () => ({ data: { statuses: [], tiers: [], temperatures: [], additive_types: [] }, loading: false, error: null }),
  useDeleteExperiment: () => ({
    mutateAsync: mockApi.deleteMutateAsync,
    isPending: false,
    error: null,
  }),
  useScanDatabase: () => mockMutation(),
  useImportExperiments: () => mockMutation(),
  useDeleteScannedExperiments: () => mockMutation(),
}))

describe('Database binder-cell catalog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows source-ready binder basics with current filter controls', async () => {
    render(
      <MemoryRouter>
        <Database />
      </MemoryRouter>
    )

    expect(screen.queryByPlaceholderText('Search...')).not.toBeInTheDocument()
    expect(screen.getByText('All Tiers')).toBeInTheDocument()
    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scan Database' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Refresh' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('A1_X2_NA_SBS_298K_abc123'))

    await waitFor(() => {
      expect(screen.getByTestId('mock-experiment-detail')).toBeInTheDocument()
    })

    expect(screen.getAllByText('SBS').length).toBeGreaterThan(0)
  })
})
