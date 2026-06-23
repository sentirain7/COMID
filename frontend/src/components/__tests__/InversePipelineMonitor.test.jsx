/**
 * Inverse design wizard ③④ tests (P5).
 *
 * Pins:
 *   - PipelineMonitor: progress counts/member statuses/ensemble display + results button
 *   - TargetVsActualPanel: per_target achievement badges, ensemble mean±SE display,
 *     curve comparison query only when there are completed layered experiments
 *   - StressStrainCompareChart: merging series with different strain grids
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import PipelineMonitor from '../inverse-design/PipelineMonitor'
import TargetVsActualPanel from '../inverse-design/TargetVsActualPanel'

const mocks = vi.hoisted(() => ({
  getInversePipelineProgress: vi.fn(),
  getInversePipelineResults: vi.fn(),
  getArrayMetricCompare: vi.fn(),
}))

vi.mock('../../api/inversePipeline', () => ({
  previewInversePlan: vi.fn(),
  approveInversePlan: vi.fn(),
  getInversePipelineProgress: mocks.getInversePipelineProgress,
  getInversePipelineResults: mocks.getInversePipelineResults,
}))

vi.mock('../../api/client', () => ({
  getArrayMetricCompare: mocks.getArrayMetricCompare,
}))

// jsdom stub for the ResizeObserver required by recharts ResponsiveContainer
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver || ResizeObserverStub

function renderWithClient(ui) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PipelineMonitor', () => {
  it('renders counts, member statuses, and ensemble marker', async () => {
    mocks.getInversePipelineProgress.mockResolvedValue({
      pipeline_id: 'pl-x',
      total: 2,
      completed: 1,
      status_counts: { completed: 1, running: 1 },
      members: [
        {
          exp_id: 'b1',
          effective_exp_id: 'b1',
          plan_exp_id: 'exp-001',
          kind: 'binder_cell',
          candidate_index: 0,
          status: 'completed',
          effective_status: 'completed',
          replicate_group_id: null,
          ensemble_ready: false,
        },
        {
          exp_id: 'ph1',
          effective_exp_id: 'lay1',
          plan_exp_id: 'exp-002',
          kind: 'layered_tensile',
          candidate_index: 0,
          status: 'cancelled',
          effective_status: 'running',
          replicate_group_id: 'rgrp_1',
          ensemble_ready: true,
        },
      ],
    })

    const onShowResults = vi.fn()
    renderWithClient(<PipelineMonitor pipelineId="pl-x" onShowResults={onShowResults} />)

    expect(await screen.findByText('completed: 1')).toBeTruthy()
    expect(screen.getByText('running: 1')).toBeTruthy()
    expect(screen.getByText('lay1')).toBeTruthy()
    expect(screen.getByText('ensemble ✓')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /results/i }))
    expect(onShowResults).toHaveBeenCalled()
  })
})

describe('TargetVsActualPanel', () => {
  const RESULTS = {
    pipeline_id: 'pl-x',
    targets: [
      {
        metric_name: 'work_of_separation',
        target_min: 50,
        target_max: null,
        direction: 'maximize',
        unit: 'mJ/m²',
      },
    ],
    candidates: [
      {
        candidate_index: 0,
        experiments: [{ exp_id: 'lay1', kind: 'layered_tensile', status: 'completed' }],
        metrics: {
          work_of_separation: {
            value: 80.0,
            uncertainty: 4.0,
            source: 'replicate_ensemble',
            n_replicates: 3,
          },
        },
        per_target: { work_of_separation: { value: 80.0, satisfied: true } },
        targets_satisfied: true,
      },
      {
        candidate_index: 1,
        experiments: [{ exp_id: 'lay2', kind: 'layered_tensile', status: 'running' }],
        metrics: {},
        per_target: { work_of_separation: { value: null, satisfied: null } },
        targets_satisfied: null,
      },
    ],
    total_experiments: 4,
    completed_experiments: 2,
  }

  it('shows ensemble mean±SE and satisfaction badges', async () => {
    mocks.getInversePipelineResults.mockResolvedValue(RESULTS)
    mocks.getArrayMetricCompare.mockResolvedValue({ metric_name: 'stress_strain_curve', experiments: [] })

    renderWithClient(<TargetVsActualPanel pipelineId="pl-x" />)

    expect(await screen.findByText('80.00')).toBeTruthy()
    expect(screen.getByText('± 4.0')).toBeTruthy()
    expect(screen.getByText('SE (n=3)')).toBeTruthy()
    expect(screen.getAllByText('met').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('pending').length).toBeGreaterThanOrEqual(1)
    // 1 completed layered experiment → curve comparison query invoked
    expect(mocks.getArrayMetricCompare).toHaveBeenCalledWith(['lay1'], 'stress_strain_curve')
  })

  it('skips curve query when no completed layered experiments', async () => {
    mocks.getInversePipelineResults.mockResolvedValue({
      ...RESULTS,
      candidates: [RESULTS.candidates[1]],
    })
    renderWithClient(<TargetVsActualPanel pipelineId="pl-x" />)
    await screen.findByText(/Target vs actual/)
    expect(mocks.getArrayMetricCompare).not.toHaveBeenCalled()
  })
})

describe('StressStrainCompareChart merge', () => {
  it('merges series with different strain grids', async () => {
    const { default: Chart } = await import('../Charts/StressStrainCompareChart')
    const { container } = render(
      <Chart
        series={[
          { label: 'a', strain: [0, 0.1], stress: [0, 5] },
          { label: 'b', strain: [0, 0.05, 0.1], stress: [0, 2, 6] },
        ]}
      />,
    )
    // The chart container should render rather than the empty notice
    expect(container.textContent).not.toContain('No stress-strain curves')
  })

  it('renders empty notice without data', async () => {
    const { default: Chart } = await import('../Charts/StressStrainCompareChart')
    render(<Chart series={[]} />)
    expect(screen.getByText(/No stress-strain curves/)).toBeTruthy()
  })
})
