import { fireEvent, render, screen } from '@testing-library/react'
import ModelCompareBar from '../Charts/ModelCompareBar'
import StructuralEvalPanel from '../mlops/StructuralEvalPanel'

const mockEval = { mutate: vi.fn(), isPending: false, data: null, error: null }
const mockTrain = { mutate: vi.fn(), isPending: false, data: null, error: null }

// vi.mock is hoisted, so it is applied before the imports above.
vi.mock('../../hooks/useApi', () => ({
  useStructuralEval: () => mockEval,
  useStructuralTrain: () => mockTrain,
}))

describe('ModelCompareBar', () => {
  it('renders both models with winner star and mean values', () => {
    const models = {
      xgboost: { rmse_mean: 0.02, rmse_std: 0.003, per_repeat: [0.02, 0.018] },
      random_forest: { rmse_mean: 0.03, rmse_std: 0.004, per_repeat: [0.03, 0.028] },
    }
    render(<ModelCompareBar models={models} winner="xgboost" />)
    expect(screen.getByText(/XGBoost/)).toBeInTheDocument()
    expect(screen.getByText('RandomForest')).toBeInTheDocument()
    // Winner has a ★ prefix — the XGBoost label includes ★
    expect(screen.getByText(/★\s*XGBoost/)).toBeInTheDocument()
    expect(screen.getByText(/0\.0200/)).toBeInTheDocument()
  })

  it('renders empty state when no models', () => {
    render(<ModelCompareBar models={{}} winner={null} />)
    expect(screen.getByText('No evaluation data.')).toBeInTheDocument()
  })
})

describe('StructuralEvalPanel', () => {
  beforeEach(() => {
    mockEval.mutate.mockClear()
    mockTrain.mutate.mockClear()
    mockEval.data = null
    mockEval.error = null
    mockTrain.data = null
  })

  it('triggers eval mutation with target on button click', () => {
    render(<StructuralEvalPanel target="density" />)
    fireEvent.click(screen.getByText('Run Competition Eval'))
    expect(mockEval.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ target: 'density' })
    )
  })

  it('renders winner badge and chart when eval data present', () => {
    mockEval.data = {
      target: 'density',
      n_samples: 165,
      n_repeats: 10,
      transform: 'identity',
      models: {
        xgboost: { rmse_mean: 0.02, rmse_std: 0.003, per_repeat: [0.02] },
        random_forest: { rmse_mean: 0.03, rmse_std: 0.004, per_repeat: [0.03] },
      },
      winner: 'xgboost',
    }
    render(<StructuralEvalPanel target="density" />)
    expect(screen.getByText(/Winner: xgboost/)).toBeInTheDocument()
    expect(screen.getByText(/n_samples=165/)).toBeInTheDocument()
  })

  it('surfaces eval error gracefully', () => {
    mockEval.data = { target: 'density', error: 'insufficient internal V7 data' }
    render(<StructuralEvalPanel target="density" />)
    expect(screen.getByText(/Cannot evaluate: insufficient/)).toBeInTheDocument()
  })

  it('shows train outcome with per-target winner model', () => {
    mockTrain.data = {
      version_id: null,
      targets_trained: ['density'],
      training_samples: 132,
      holdout_samples: 33,
      promoted: false,
      per_target_holdout_rmse: { density: 0.019 },
      model_types: { density: 'xgboost' },
      notes: [],
    }
    render(<StructuralEvalPanel target="density" />)
    expect(screen.getByText(/dry-run \/ not promoted/)).toBeInTheDocument()
    expect(screen.getByText('xgboost')).toBeInTheDocument()
  })
})
