import { useStructuralEval, useStructuralTrain } from '../../hooks/useApi'
import ModelCompareBar from '../Charts/ModelCompareBar'

/**
 * V7 structural ML on-demand panel — triggers XGBoost vs RandomForest competition
 * (random repeated evaluation) and challenger training (dry-run) via user buttons.
 *
 * Evaluation uses only internal (GAFF2) data, and because it includes model
 * training the response can be slow, so it does not auto-poll (explicit buttons).
 * ``target`` is inherited directly from the parent (DiagnosticsSection) selection.
 */
const N_REPEATS = 10

function StructuralEvalPanel({ target }) {
  const evalMutation = useStructuralEval()
  const trainMutation = useStructuralTrain()

  const evalData = evalMutation.data
  const trainData = trainMutation.data
  const evalErr = evalMutation.error?.message || evalMutation.error
  const trainErr = trainMutation.error?.message || trainMutation.error

  return (
    <div className="mt-4 border-t border-slate-700 pt-3">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <h3 className="text-xs font-medium text-slate-400">
          V7 Structural — XGBoost vs RandomForest
        </h3>
        <span className="text-[10px] text-slate-500">target: {target}</span>
        <div className="flex-1" />
        <button
          className="btn-secondary text-xs px-2 py-1"
          onClick={() => evalMutation.mutate({ target, n_repeats: N_REPEATS })}
          disabled={evalMutation.isPending}
          title={`Random-split evaluation on internal GAFF2 data, ${N_REPEATS} repeats (XGB vs RF)`}
        >
          {evalMutation.isPending ? 'Evaluating…' : 'Run Competition Eval'}
        </button>
        <button
          className="btn-secondary text-xs px-2 py-1"
          onClick={() => trainMutation.mutate({ register: false })}
          disabled={trainMutation.isPending}
          title="V7 challenger training (dry-run — registry unchanged, reports winner model per property)"
        >
          {trainMutation.isPending ? 'Training…' : 'Train (dry-run)'}
        </button>
      </div>

      {evalErr && <p className="text-amber-300 text-xs mb-2">Evaluation failed: {String(evalErr)}</p>}
      {evalData?.error && (
        <p className="text-amber-300 text-xs mb-2">Cannot evaluate: {evalData.error}</p>
      )}

      {evalData && !evalData.error && (
        <div className="mb-3">
          <div className="flex flex-wrap items-center gap-2 mb-2 text-[10px]">
            {evalData.winner && (
              <span className="px-1.5 py-0.5 rounded border bg-emerald-500/10 border-emerald-500/40 text-emerald-300">
                Winner: {evalData.winner}
              </span>
            )}
            <span className="text-slate-400">
              n_samples={evalData.n_samples} · n_repeats={evalData.n_repeats}
            </span>
            {evalData.transform && evalData.transform !== 'identity' && (
              <span className="text-slate-500">transform: {evalData.transform}</span>
            )}
          </div>
          <ModelCompareBar models={evalData.models} winner={evalData.winner} />
        </div>
      )}

      {trainErr && <p className="text-amber-300 text-xs mb-2">Training failed: {String(trainErr)}</p>}

      {trainData && (
        <div className="text-xs bg-slate-800/60 rounded p-2">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className="text-slate-400">
              Training samples {trainData.training_samples} · holdout {trainData.holdout_samples}
            </span>
            <span
              className={`px-1.5 py-0.5 rounded border text-[10px] ${
                trainData.promoted
                  ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                  : 'bg-slate-700/60 border-slate-600 text-slate-300'
              }`}
            >
              {trainData.promoted ? 'promoted' : 'dry-run / not promoted'}
            </span>
          </div>
          {trainData.targets_trained?.length > 0 && (
            <table className="w-full text-[11px] mt-1">
              <thead>
                <tr className="text-slate-500 text-left">
                  <th className="py-0.5 pr-2">Property</th>
                  <th className="py-0.5 pr-2">Winner model</th>
                  <th className="py-0.5">holdout RMSE</th>
                </tr>
              </thead>
              <tbody>
                {trainData.targets_trained.map((t) => (
                  <tr key={t} className="text-slate-300">
                    <td className="py-0.5 pr-2 font-mono">{t}</td>
                    <td className="py-0.5 pr-2">{trainData.model_types?.[t] || '—'}</td>
                    <td className="py-0.5 tabular-nums">
                      {trainData.per_target_holdout_rmse?.[t] != null
                        ? trainData.per_target_holdout_rmse[t].toFixed(4)
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

export default StructuralEvalPanel
