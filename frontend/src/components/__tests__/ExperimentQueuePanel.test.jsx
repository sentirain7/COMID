import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ExperimentQueuePanel from '../ExperimentQueuePanel'

vi.mock('../../hooks/useApi', () => ({
  useBatchCancelExperiments: () => ({ mutateAsync: vi.fn() }),
  useBatchDeleteExperiments: () => ({ mutateAsync: vi.fn() }),
  useBatchRetryExperiments: () => ({ mutateAsync: vi.fn() }),
  useCancelExperiment: () => ({ mutateAsync: vi.fn() }),
  useDeleteExperiment: () => ({ mutateAsync: vi.fn() }),
  useRetryExperiment: () => ({ mutateAsync: vi.fn() }),
}))

vi.mock('../../hooks/useNotification', () => ({
  useNotification: () => ({
    notification: null,
    notify: vi.fn(),
    dismiss: vi.fn(),
  }),
}))

function renderPanel(props = {}) {
  return render(
    <MemoryRouter>
      <ExperimentQueuePanel {...props} />
    </MemoryRouter>
  )
}

describe('ExperimentQueuePanel', () => {
  it('renders with empty experiments list', () => {
    renderPanel({ experiments: [] })
    expect(screen.getByText('Experiment Queue')).toBeInTheDocument()
    expect(screen.getByText('No experiments in queue')).toBeInTheDocument()
  })

  it('renders experiment with status badge', () => {
    const experiments = [
      {
        exp_id: 'A1_X1_NA_none_298K_abc123',
        status: 'running',
        created_at: '2026-03-20T10:00:00Z',
      },
    ]
    renderPanel({ experiments, runningJobs: [] })
    // The exp_id is rendered as parsed tokens
    expect(screen.getByText('A1')).toBeInTheDocument()
    // Status badge renders — StatusBadge component displays status text
    expect(screen.getByText('running')).toBeInTheDocument()
  })

  it('renders single molecule experiment ids with a visible temperature token', () => {
    const experiments = [
      {
        exp_id: 'SM_U-AS-Thio-0293_293K_abc123',
        status: 'completed',
        created_at: '2026-03-20T10:00:00Z',
      },
    ]
    renderPanel({ experiments, runningJobs: [] })

    expect(screen.getByText('SM')).toBeInTheDocument()
    expect(screen.getByText('U-AS-Thio-0293')).toBeInTheDocument()
    expect(screen.getAllByText('293K')).toHaveLength(1)
  })

  it('renders temperature metadata for legacy single molecule experiment ids', () => {
    const experiments = [
      {
        exp_id: 'SM_U-AS-Thio-0293_abc123',
        status: 'completed',
        temperature_k: 293,
        created_at: '2026-03-20T10:00:00Z',
      },
    ]
    renderPanel({ experiments, runningJobs: [] })

    expect(screen.getByText('SM')).toBeInTheDocument()
    expect(screen.getByText('U-AS-Thio-0293')).toBeInTheDocument()
    expect(screen.getAllByText('293K')).toHaveLength(1)
  })

  it('shows batch cancel/delete buttons when experiments are selected', () => {
    const experiments = [
      {
        exp_id: 'A1_X1_NA_none_298K_abc123',
        status: 'running',
        created_at: '2026-03-20T10:00:00Z',
      },
      {
        exp_id: 'A1_X1_NA_none_298K_def456',
        status: 'completed',
        created_at: '2026-03-20T11:00:00Z',
      },
    ]
    renderPanel({ experiments, runningJobs: [] })

    // Select the first checkbox (not the header checkbox)
    const checkboxes = screen.getAllByRole('checkbox')
    // checkboxes[0] = header select-all, checkboxes[1] = first row, checkboxes[2] = second row
    fireEvent.click(checkboxes[1])

    // Batch toolbar should appear with cancel button (running is cancelable)
    expect(screen.getByText(/1 selected/)).toBeInTheDocument()
    expect(screen.getByText(/Bulk Stop/)).toBeInTheDocument()

    // Select the second checkbox (completed is deletable)
    fireEvent.click(checkboxes[2])
    expect(screen.getByText(/2 selected/)).toBeInTheDocument()
    expect(screen.getByText(/Bulk Delete/)).toBeInTheDocument()
  })

  it('renders total count from prop', () => {
    renderPanel({ experiments: [], totalCount: 42 })
    expect(screen.getByText('(42 total)')).toBeInTheDocument()
  })

  it('shows loading spinner when loading prop is true', () => {
    renderPanel({ experiments: [], loading: true })
    // When loading, the table body is replaced by a spinner - "No experiments" should not appear
    expect(screen.queryByText('No experiments in queue')).not.toBeInTheDocument()
  })

  it('renders building row with numeric build_progress_percent', () => {
    const experiments = [
      {
        exp_id: 'A1_X1_NA_none_298K_buildrow',
        status: 'building',
        created_at: '2026-04-15T10:00:00Z',
      },
    ]
    const runningJobs = [
      {
        exp_id: 'A1_X1_NA_none_298K_buildrow',
        status: 'building',
        build_phase: 'generating_ff_params',
        build_phase_label: 'Generating FF parameters',
        build_progress_percent: 62.5,
        pipeline_elapsed_seconds: 45,
      },
    ]
    renderPanel({ experiments, runningJobs })
    // Integer percent span renders alongside the label
    expect(screen.getByText('63%')).toBeInTheDocument()
    expect(screen.getByText('Generating FF parameters')).toBeInTheDocument()
  })

  it('prefers pipelineElapsedSeconds over legacy elapsed/wallTimeSeconds', () => {
    const experiments = [
      {
        exp_id: 'A1_X1_NA_none_298K_elapsedpref',
        status: 'running',
        created_at: '2026-04-15T10:00:00Z',
        wall_time_seconds: 30,
        pipeline_elapsed_seconds: 7500, // 2h 5m
      },
    ]
    const runningJobs = [
      {
        exp_id: 'A1_X1_NA_none_298K_elapsedpref',
        status: 'running',
        elapsed: '10s',
        current_step: 1,
        total_steps: 10,
        pipeline_elapsed_seconds: 7500,
      },
    ]
    renderPanel({ experiments, runningJobs })
    expect(screen.getByText('2h 5m')).toBeInTheDocument()
    expect(screen.queryByText('10s')).not.toBeInTheDocument()
  })

  it('falls back to legacy wall time when pipelineElapsedSeconds missing', () => {
    const experiments = [
      {
        exp_id: 'A1_X1_NA_none_298K_legacy',
        status: 'completed',
        created_at: '2026-04-15T10:00:00Z',
        wall_time_seconds: 300, // 5m
      },
    ]
    renderPanel({ experiments, runningJobs: [] })
    expect(screen.getByText('5m')).toBeInTheDocument()
  })
})
