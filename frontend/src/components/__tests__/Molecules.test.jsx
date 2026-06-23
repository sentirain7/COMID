/**
 * v00.99.53 + v00.99.66: /molecules FF notification rendering + disabled-scope.
 *
 * v00.99.66: the action bar button is now labelled "Generate (N)" or
 * "Regen (N)" (N = genTarget), not "Generate Selected FF". Tests select it
 * by the leading "Generate (" prefix which is stable across counts.
 *
 * Covers:
 *   Path A (NotificationBanner):
 *     - success → blue info banner
 *     - eligible=0 → amber warning banner
 *     - mutation error → red alert banner (role="alert")
 *     - dismiss click unmounts banner
 *     - banner + selection action bar render together (no overlap)
 *   Path B (disabled scope):
 *     - batch_kind='public' running → "Generate (N)" stays enabled
 *     - batch_kind='admin' running → button disabled
 */
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Molecules from '../Molecules'

// Mock molecules — a single organic_curated_artifact mol that can be checked
const mockMolecules = [
  {
    mol_id: 'U-AS-Thio-0293',
    category: 'asphaltene',
    molecular_weight: 356.0,
    atom_count: 42,
    structure_file: 'asphalt_binder/U-AS-Thio-0293.mol',
    aging_state: 'non_aging',
    base_id: 'Thiophenol',
    source: 'asphalt_binder',
    route: 'organic_curated_artifact',
    is_submittable: true,
  },
  {
    mol_id: 'FirstAdditive',
    category: null,
    molecular_weight: 150.0,
    atom_count: 16,
    structure_file: 'additives/FirstAdditive.mol',
    aging_state: null,
    base_id: 'First Additive',
    source: 'additives',
    route: 'organic_curated_artifact',
    is_submittable: true,
  },
  {
    mol_id: 'TargetAdditive',
    category: null,
    molecular_weight: 180.0,
    atom_count: 20,
    structure_file: 'additives/TargetAdditive.mol',
    aging_state: null,
    base_id: 'Target Additive',
    source: 'additives',
    route: 'organic_curated_artifact',
    is_submittable: true,
  },
]

// Mutable hook-return overrides so individual tests can tweak them
const mutationCaptured = { mutate: null, isPending: false }
const progressState = { data: null }

vi.mock('../../hooks/useMolecules', () => ({
  useMolecules: () => ({
    molecules: mockMolecules,
    loading: false,
    error: null,
    total: mockMolecules.length,
    refetch: vi.fn(),
  }),
}))

vi.mock('../../hooks/useApi', () => ({
  useAdminArtifactStatus: () => ({ data: { rows: [] } }),
  useAdminGenerateArtifact: () => ({
    mutate: vi.fn(),
    isPending: false,
    variables: null,
  }),
  useAdminGenerateAll: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminGenerateSelected: () => ({
    // Capture the (variables, options) pair so tests can fire onSuccess/onError manually.
    mutate: (variables, options) => {
      mutationCaptured.mutate = { variables, options }
    },
    get isPending() {
      return mutationCaptured.isPending
    },
  }),
  useAdminCancelBatch: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminResetBatch: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminDiagnoseArtifact: () => ({ mutate: vi.fn() }),
  useAdminBatchProgress: () => progressState,
}))

// v01.04.17: Mock useSubmissionEIntraMethod hook used by Molecules.jsx
vi.mock('../../hooks/useSubmissionEIntraMethod', () => ({
  useSubmissionEIntraMethod: () => ({
    settings: { default_e_intra_method: 'single_molecule_vacuum_adaptive_cutoff' },
    defaultEIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
    effectiveEIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
    selectedEIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
    setSelectedEIntraMethod: vi.fn(),
  }),
}))

vi.mock('../../api/client', () => ({
  getMoleculeStructure: vi.fn().mockResolvedValue({ xyz: '', bonds: [] }),
}))

// v01.04.17: Mock ScanDatabaseModal to avoid deep hook dependencies
vi.mock('../ScanDatabaseModal', () => ({
  default: () => null,
}))

function renderPage(initialEntries = ['/molecules']) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <Molecules />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Check a mol and click the selection "Generate (N)" button. */
function selectAndSubmit() {
  // Click the row checkbox (first <input type=checkbox> in the mol row).
  const rowCheckboxes = screen.getAllByRole('checkbox')
  // rowCheckboxes[0] is the select-all in the thead; rowCheckboxes[1] is the row
  fireEvent.click(rowCheckboxes[1])
  const btn = screen.getByRole('button', { name: /^Generate \(/i })
  fireEvent.click(btn)
}

describe('Molecules page — FF notification rendering', () => {
  beforeEach(() => {
    mutationCaptured.mutate = null
    mutationCaptured.isPending = false
    progressState.data = null
  })

  it('shows info banner on successful Generate Selected FF', () => {
    renderPage()
    selectAndSubmit()
    expect(mutationCaptured.mutate).not.toBeNull()
    act(() => {
      mutationCaptured.mutate.options.onSuccess({
        eligible_count: 1,
        skipped: [],
        unmatched_mol_ids: [],
      })
    })
    const banner = screen.getByTestId('molecules-notification')
    expect(banner).toHaveAttribute('role', 'status')
    expect(banner).toHaveAttribute('aria-live', 'polite')
    expect(banner).toHaveTextContent(/Selected batch started: 1 molecule/i)
  })

  it('shows warning banner with policy-gate reason when skipped[0] has message', () => {
    renderPage()
    selectAndSubmit()
    act(() => {
      mutationCaptured.mutate.options.onSuccess({
        eligible_count: 0,
        skipped: [{ mol_id: 'U-AS-Thio-0293', message: 'locked by another generation' }],
        unmatched_mol_ids: [],
      })
    })
    const banner = screen.getByTestId('molecules-notification')
    expect(banner).toHaveTextContent(/Nothing eligible in selection/i)
    expect(banner).toHaveTextContent(/U-AS-Thio-0293: locked by another generation/)
    expect(banner.className).toMatch(/amber/)
  })

  it('shows warning banner with unmatched hint when server classifies as complete/non-organic', () => {
    renderPage()
    selectAndSubmit()
    act(() => {
      mutationCaptured.mutate.options.onSuccess({
        eligible_count: 0,
        skipped: [],
        unmatched_mol_ids: ['U-SA-Squalane-0293'],
      })
    })
    const banner = screen.getByTestId('molecules-notification')
    expect(banner).toHaveTextContent(/Nothing eligible in selection/i)
    expect(banner).toHaveTextContent(/U-SA-Squalane-0293/)
    expect(banner).toHaveTextContent(/complete \/ non-organic \/ mol_id mismatch/)
  })

  it('shows error banner with role=alert on mutation failure', () => {
    renderPage()
    selectAndSubmit()
    act(() => {
      mutationCaptured.mutate.options.onError({
        message: 'Network Error',
        response: { data: { detail: { message: 'backend down' } } },
      })
    })
    const banner = screen.getByTestId('molecules-notification')
    expect(banner).toHaveAttribute('role', 'alert')
    expect(banner).toHaveAttribute('aria-live', 'assertive')
    expect(banner).toHaveTextContent('backend down')
  })

  it('dismiss button unmounts the banner', () => {
    renderPage()
    selectAndSubmit()
    act(() => {
      mutationCaptured.mutate.options.onSuccess({ eligible_count: 1 })
    })
    expect(screen.queryByTestId('molecules-notification')).not.toBeNull()
    fireEvent.click(screen.getByTestId('molecules-notification-dismiss'))
    expect(screen.queryByTestId('molecules-notification')).toBeNull()
  })

  it('banner + selection action bar coexist in the DOM (no overlap)', () => {
    renderPage()
    selectAndSubmit()
    act(() => {
      mutationCaptured.mutate.options.onSuccess({ eligible_count: 1 })
    })
    expect(screen.getByTestId('molecules-notification')).toBeInTheDocument()
    // Selection action bar shows the checked count. v00.99.66: text is now
    // just "1 selected" plus colored status dots — no extra suffix.
    expect(screen.getByText(/1 selected/)).toBeInTheDocument()
  })
})

describe('Molecules page — disabled scope (Path B)', () => {
  beforeEach(() => {
    mutationCaptured.mutate = null
    mutationCaptured.isPending = false
    progressState.data = null
  })

  it('keeps the Generate (N) button enabled during a PUBLIC batch', () => {
    // v00.99.66: the inline "public batch in progress" hint was removed from the
    // selection action bar; the behavioural guarantee (enabled-during-public,
    // disabled-during-admin) is what matters here.
    progressState.data = { running: true, batch_kind: 'public', completed: 0, total: 1 }
    renderPage()
    const rowCheckboxes = screen.getAllByRole('checkbox')
    fireEvent.click(rowCheckboxes[1])
    const btn = screen.getByRole('button', { name: /^Generate \(/i })
    expect(btn).not.toBeDisabled()
  })

  it('disables Generate Selected FF during an ADMIN batch', () => {
    progressState.data = { running: true, batch_kind: 'admin', completed: 0, total: 2 }
    renderPage()
    const rowCheckboxes = screen.getAllByRole('checkbox')
    fireEvent.click(rowCheckboxes[1])
    const btn = screen.getByRole('button', { name: /^Generate \(/i })
    expect(btn).toBeDisabled()
  })
})

describe('Molecules page — mol_id deep link', () => {
  beforeEach(() => {
    mutationCaptured.mutate = null
    mutationCaptured.isPending = false
    progressState.data = null
  })

  it('switches to the target tab and keeps the requested molecule selected', async () => {
    renderPage(['/molecules?mol_id=TargetAdditive'])

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Additives \(2\)/i })).toHaveAttribute(
        'aria-pressed',
        'true',
      )
    })

    expect(screen.getByText('FirstAdditive')).toBeInTheDocument()

    // The target name appears in both the table row and the preview header
    // only if the fallback selection effect did not overwrite the deep link
    // with the first additive in the tab.
    await waitFor(() => {
      expect(screen.getAllByText('TargetAdditive')).toHaveLength(2)
    })
  })
})
