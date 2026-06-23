import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Header from '../Layout/Header'

const mockState = {
  health: {
    status: 'limited',
    severity: 'warn',
    version: '01.02.08',
    can_submit_jobs: false,
    components: {
      database: { status: 'ready', message: 'ok', latency_ms: 12.3 },
      redis: { status: 'limited', message: 'slow', latency_ms: 220.5 },
      celery_workers: { status: 'down', message: 'no workers', latency_ms: null },
    },
  },
  healthLoading: false,
}

vi.mock('../../hooks/useApi', () => ({
  useHealth: () => ({ data: mockState.health, loading: mockState.healthLoading }),
  useSystemStats: () => ({ data: { cpu_percent: 10, memory_percent: 20 }, loading: false }),
  useGPUStats: () => ({ data: { gpus: [{ utilization: 33 }] }, loading: false }),
  useSettings: () => ({ settings: { gpu_enabled: true }, loading: false, error: null, update: vi.fn() }),
}))

describe('Header observability', () => {
  it('renders detailed health fields from API', () => {
    mockState.healthLoading = false
    mockState.health = {
      status: 'limited',
      severity: 'warn',
      version: '01.02.08',
      can_submit_jobs: false,
      components: {
        database: { status: 'ready', message: 'ok', latency_ms: 12.3 },
        redis: { status: 'limited', message: 'slow', latency_ms: 220.5 },
        celery_workers: { status: 'down', message: 'no workers', latency_ms: null },
      },
    }

    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>
    )

    // Header renders COMPONENT_LABELS: DB, Redis, Worker
    expect(screen.getByText('DB')).toBeInTheDocument()
    expect(screen.getByText('Redis')).toBeInTheDocument()
    expect(screen.getByText('Worker')).toBeInTheDocument()
    // Version
    expect(screen.getByText('v01.02.08')).toBeInTheDocument()
    // System stats
    expect(screen.getByText('10%')).toBeInTheDocument()
    expect(screen.getByText('20%')).toBeInTheDocument()
  })

  it('shows neutral state while health payload is not loaded', () => {
    mockState.healthLoading = true
    mockState.health = null

    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>
    )

    // Version fallback
    expect(screen.getByText('v-')).toBeInTheDocument()
    // Component labels still render
    expect(screen.getByText('DB')).toBeInTheDocument()
    expect(screen.getByText('Redis')).toBeInTheDocument()
    expect(screen.getByText('Worker')).toBeInTheDocument()
  })
})
