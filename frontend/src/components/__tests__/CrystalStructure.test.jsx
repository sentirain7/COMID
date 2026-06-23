import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import CrystalStructure from '../CrystalStructure'

const mockApi = vi.hoisted(() => ({
  batchMutate: vi.fn(),
  navigate: vi.fn(),
}))

vi.mock('../MoleculeViewer', () => ({
  default: () => null,
  MoleculeViewer: () => null,
  SimpleViewer: () => null,
  getElementColorCss: () => 'rgb(128,128,128)',
  normalizeElementSymbol: (s) => s,
  ELEMENT_COLORS: {},
}))

vi.mock('../DataSyncModal', () => ({
  default: () => null,
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockApi.navigate,
  }
})

vi.mock('../../hooks/useApiCrystalStructures', () => ({
  useCrystalStructures: () => ({
    data: { items: [] },
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useCrystalStructurePreview: () => ({
    data: null,
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useCreateCrystalStructure: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
    error: null,
  }),
  useDeleteCrystalStructure: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
    error: null,
  }),
  useBatchGenerateCrystalSizes: () => ({
    mutate: mockApi.batchMutate,
    mutateAsync: vi.fn(),
    isPending: false,
    error: null,
    data: null,
  }),
}))

describe('CrystalStructure (single-job create)', () => {
  const renderWithProviders = (ui) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryClientProvider>
    )
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders create panel and triggers batch generate', async () => {
    renderWithProviders(<CrystalStructure mode="create" />)

    expect(screen.getByRole('button', { name: 'Data Sync' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Scan Database' })).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Material' })).toBeInTheDocument()

    const batchButton = screen.getByRole('button', { name: /Batch All Sizes/i })
    expect(batchButton).toBeInTheDocument()

    fireEvent.click(batchButton)

    expect(mockApi.batchMutate).toHaveBeenCalled()
  })
})
