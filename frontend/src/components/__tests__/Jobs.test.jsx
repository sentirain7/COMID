import { render, screen } from '@testing-library/react'
import Jobs from '../Jobs'

vi.mock('../../hooks/useApi', () => ({
  useQueueStats: () => ({ data: null, loading: false, execute: vi.fn() }),
  useJobs: () => ({ data: { jobs: [] }, loading: false, execute: vi.fn() }),
  useDeleteJob: () => ({ mutateAsync: vi.fn() }),
  useCancelJob: () => ({ mutateAsync: vi.fn() }),
  useRetryJob: () => ({ mutateAsync: vi.fn() }),
  useDeleteAllCompletedJobs: () => ({ mutateAsync: vi.fn() }),
}))

describe('Jobs', () => {
  it('renders without crashing', () => {
    render(<Jobs />)
    expect(screen.getByText('Job Queue')).toBeInTheDocument()
  })
})
