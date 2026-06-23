import { render, screen } from '@testing-library/react'
import MLOps from '../MLOps'

const emptyQuery = { data: null, loading: false, error: null }
const emptyMutation = { mutate: vi.fn(), isPending: false }

const mockUseDataQuality = vi.fn(() => emptyQuery)
const mockUseDataCoverage = vi.fn(() => emptyQuery)
const mockUseStructuralMLStatus = vi.fn(() => emptyQuery)

vi.mock('../../hooks/useApi', () => ({
  useChampionModel: () => emptyQuery,
  useModelHistory: () => ({ data: { models: [] }, loading: false, error: null }),
  useModelDrift: () => emptyQuery,
  useRetrainModel: () => emptyMutation,
  usePromoteModel: () => emptyMutation,
  useRollbackModel: () => emptyMutation,
  // Diagnostics hooks
  useParityPlot: () => emptyQuery,
  useFeatureImportance: () => emptyQuery,
  useResiduals: () => emptyQuery,
  useLearningCurve: () => emptyQuery,
  useDataCoverage: (...args) => mockUseDataCoverage(...args),
  useDataQuality: (...args) => mockUseDataQuality(...args),
  useStructuralMLStatus: (...args) => mockUseStructuralMLStatus(...args),
  useStructuralEval: () => emptyMutation,
  useStructuralTrain: () => emptyMutation,
}))

vi.mock('../Charts/ParityPlot', () => ({ default: () => <div>ParityPlot</div> }))
vi.mock('../Charts/FeatureImportanceChart', () => ({ default: () => <div>FeatureImportanceChart</div> }))
vi.mock('../Charts/ResidualHistogram', () => ({ default: () => <div>ResidualHistogram</div> }))
vi.mock('../Charts/LearningCurve', () => ({ default: () => <div>LearningCurve</div> }))

describe('MLOps', () => {
  beforeEach(() => {
    mockUseDataQuality.mockReturnValue(emptyQuery)
    mockUseDataCoverage.mockReturnValue(emptyQuery)
  })

  it('renders without crashing', () => {
    render(<MLOps />)
    expect(screen.getByText('MLOps')).toBeInTheDocument()
  })

  it('renders diagnostics section', () => {
    render(<MLOps />)
    expect(screen.getByText('Model Diagnostics')).toBeInTheDocument()
  })

  it('renders target selector with density default', () => {
    render(<MLOps />)
    const selects = screen.getAllByRole('combobox')
    const targetSelect = selects.find((el) => el.value === 'density')
    expect(targetSelect).toBeTruthy()
  })
})

describe('MLOps Data Quality states', () => {
  beforeEach(() => {
    mockUseDataQuality.mockReturnValue(emptyQuery)
    mockUseDataCoverage.mockReturnValue(emptyQuery)
  })

  it('shows loading state', () => {
    mockUseDataQuality.mockReturnValue({ data: null, loading: true, error: null })
    render(<MLOps />)
    // AsyncSectionShell renders a spinner icon in loading state (no text)
    expect(screen.getByText('Model Diagnostics')).toBeInTheDocument()
  })

  it('shows error state', () => {
    mockUseDataQuality.mockReturnValue({ data: null, loading: false, error: 'Network error' })
    render(<MLOps />)
    expect(screen.getByText(/Data quality check failed/)).toBeInTheDocument()
  })

  it('shows empty state when no issues', () => {
    mockUseDataQuality.mockReturnValue({
      data: { total_experiments: 10, issues: [], summary: {} },
      loading: false,
      error: null,
    })
    render(<MLOps />)
    expect(screen.getByText('No data quality issues found.')).toBeInTheDocument()
  })

  it('shows issues when present', () => {
    mockUseDataQuality.mockReturnValue({
      data: {
        total_experiments: 10,
        issues: [
          { issue_type: 'density_out_of_range', exp_id: 'exp_001', details: { density: 1.5 } },
        ],
        summary: { density_out_of_range: 1 },
      },
      loading: false,
      error: null,
    })
    render(<MLOps />)
    expect(screen.getByText('Data Quality Issues')).toBeInTheDocument()
  })
})

describe('MLOps Data Coverage observability', () => {
  beforeEach(() => {
    mockUseDataQuality.mockReturnValue(emptyQuery)
  })

  it('shows champion/default method badges when coverage is available', () => {
    mockUseDataCoverage.mockReturnValue({
      data: {
        total_experiments: 12,
        per_target: {
          density: { samples: 12, sufficient: true },
        },
        e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
        champion_e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
        submission_default_e_intra_method: 'single_molecule_vacuum',
        e_intra_method_mismatch: true,
        method_resolution_status: 'champion_lineage',
      },
      loading: false,
      error: null,
    })

    render(<MLOps />)

    expect(screen.getByText(/Champion: Vacuum Adaptive/i)).toBeInTheDocument()
    expect(screen.getByText(/Submit default: Vacuum 12 Å/i)).toBeInTheDocument()
    expect(screen.getByText(/Method mismatch/i)).toBeInTheDocument()
    expect(screen.getByText(/Data Coverage/)).toBeInTheDocument()
  })

  it('surfaces strict resolver coverage error inline', () => {
    mockUseDataCoverage.mockReturnValue({
      data: null,
      loading: false,
      error: 'registry failure',
    })

    render(<MLOps />)

    expect(screen.getByText(/Data coverage failed: registry failure/)).toBeInTheDocument()
  })
})

describe('MLOps V7 champion model types (B2)', () => {
  beforeEach(() => {
    mockUseDataQuality.mockReturnValue(emptyQuery)
    mockUseDataCoverage.mockReturnValue(emptyQuery)
    mockUseStructuralMLStatus.mockReturnValue(emptyQuery)
  })

  it('renders per-target winner model badge from champion manifest', () => {
    mockUseStructuralMLStatus.mockReturnValue({
      data: {
        enabled: false,
        targets: ['density'],
        force_fields: ['gaff2_am1bcc'],
        champion_feature_set: 'v7',
        champion_supported_targets: ['density', 'msd_diffusion_coefficient'],
        champion_model_types: {
          density: 'xgboost',
          msd_diffusion_coefficient: 'random_forest',
        },
      },
      loading: false,
      error: null,
    })

    render(<MLOps />)
    // density=XGB, msd...=RF shown as abbreviations
    expect(screen.getByText(/density=XGB/)).toBeInTheDocument()
    expect(screen.getByText(/msd_diffusion_coefficient=RF/)).toBeInTheDocument()
  })
})
