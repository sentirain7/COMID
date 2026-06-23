import { render, screen } from '@testing-library/react'
import Dashboard from '../Dashboard'

vi.mock('../../hooks/useApi', () => ({
  useQueueStatsLive: () => ({ data: {}, loading: false }),
  useExperiments: () => ({ data: { experiments: [] }, loading: false, execute: vi.fn() }),
  useGPUStats: () => ({ data: {}, loading: false }),
  useRunningJobs: () => ({ data: { jobs: [] }, loading: false }),
  useCEDByAdditive: () => ({ data: { points: [] }, loading: false }),
  useExperimentEvents: () => ({ eventsByExp: {} }),
}))

vi.mock('../StatusPanel', () => ({ default: () => <div>StatusPanel</div> }))
vi.mock('../ExperimentQueuePanel', () => ({ default: () => <div>ExperimentQueuePanel</div> }))
vi.mock('../Charts/DensityChart', () => ({ default: () => <div>DensityChart</div> }))
vi.mock('../Charts/GPUUtilizationChart', () => ({ default: () => <div>GPUUtilizationChart</div> }))
vi.mock('../Charts/CEDChart', () => ({ default: () => <div>CEDChart</div> }))

describe('Dashboard', () => {
  it('renders without crashing', () => {
    render(<Dashboard />)
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
  })
})
