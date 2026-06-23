import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Experiments from '../Experiments'

const mockRetry = vi.fn().mockResolvedValue({ status: 'queued' })

vi.mock('../../hooks/useApi', () => ({
  useExperiments: () => ({
    data: {
      experiments: [
        {
          exp_id: 'exp_test_001',
          status: 'failed',
          run_tier: 'screening',
          temperature_k: 298,
          target_atoms: 100000,
          metrics: { density: 1.0, ced: 100.0 },
          created_at: new Date().toISOString(),
        },
      ],
    },
    loading: false,
    execute: vi.fn(),
  }),
  useDeleteExperiment: () => ({ mutateAsync: vi.fn() }),
  useCancelExperiment: () => ({ mutateAsync: vi.fn() }),
  useRetryExperiment: () => ({ mutateAsync: mockRetry }),
  useBatchCancelExperiments: () => ({ mutateAsync: vi.fn() }),
  useBatchDeleteExperiments: () => ({ mutateAsync: vi.fn() }),
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    cancelExperiment: vi.fn(),
    getExportFormats: vi.fn(async () => ({ formats: { csv: { available: true }, xlsx: { available: false } } })),
    exportExperiments: vi.fn(),
  }
})

describe('Experiments', () => {
  it('renders list and triggers retry mutation', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))

    render(
      <MemoryRouter>
        <Experiments />
      </MemoryRouter>
    )

    expect(screen.getByText('Experiments')).toBeInTheDocument()
    expect(screen.getByText('exp_test_001')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('Retry'))
    expect(mockRetry).toHaveBeenCalledWith('exp_test_001')
    expect(await screen.findByText(/Retry submitted for exp_test_001/)).toBeInTheDocument()
  })
})
