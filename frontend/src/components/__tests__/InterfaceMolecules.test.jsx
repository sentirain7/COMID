import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import InterfaceMolecules from '../InterfaceMolecules'

vi.mock('../MoleculeViewer', () => ({
  default: () => null,
  MoleculeViewer: () => null,
  SimpleViewer: () => null,
}))

vi.mock('../DataSyncModal', () => ({
  default: () => null,
}))

vi.mock('../../hooks/useApiInterfaceMolecules', () => ({
  useInterfaceMolecules: () => ({
    data: { items: [] },
    loading: false,
    error: null,
  }),
  useInterfaceMoleculeCells: () => ({
    data: { items: [] },
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useInterfaceMoleculeCellPreview: () => ({
    data: null,
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useInterfaceMoleculePreview: () => ({
    data: null,
    loading: false,
    error: null,
    execute: vi.fn(),
  }),
  useDeleteInterfaceMoleculeCell: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
    error: null,
  }),
  useBatchGenerateInterfaceMoleculeCells: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
    error: null,
    data: null,
  }),
}))

describe('InterfaceMolecules', () => {
  const renderWithProviders = (ui) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryClientProvider>
    )
  }

  it('shows Data Sync as the top-level asset action instead of Scan Database', () => {
    renderWithProviders(<InterfaceMolecules mode="create" />)

    expect(screen.getByRole('button', { name: 'Data Sync' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Scan Database' })).not.toBeInTheDocument()
  })
})
