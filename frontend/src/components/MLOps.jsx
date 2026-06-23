import { useState } from 'react'
import {
  useChampionModel,
  useModelDrift,
  useModelHistory,
  usePromoteModel,
  useRetrainModel,
  useRollbackModel,
} from '../hooks/useApi'
import { AsyncSectionShell } from './shared'
import ChampionMetricsTable from './mlops/ChampionMetricsTable'
import DiagnosticsSection from './mlops/DiagnosticsSection'

function MLOps() {
  const [historyLimit, setHistoryLimit] = useState(20)
  const [historyStatus, setHistoryStatus] = useState('')

  const { data: champion, loading: championLoading, error: championError } = useChampionModel()
  const { data: historyData, loading: historyLoading, error: historyError } = useModelHistory({
    limit: Number(historyLimit) || 20,
    status: historyStatus || undefined,
  })
  const { data: drift, loading: driftLoading, error: driftError } = useModelDrift()

  const retrainMutation = useRetrainModel()
  const promoteMutation = usePromoteModel()
  const rollbackMutation = useRollbackModel()

  const history = historyData?.models || []

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-white">MLOps</h1>
        <p className="text-slate-400 text-sm mt-1">Model registry, drift checks, and promotion controls</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">Champion Model</h2>
          <AsyncSectionShell
            loading={championLoading}
            error={championError}
            empty={!champion && 'No champion metadata.'}
            minHeight="min-h-[80px]"
          >
            {champion && (
              <div className="space-y-1 text-sm">
                <p className="text-white font-mono text-xs">{champion.version_id}</p>
                <p className="text-slate-300">status: {champion.status}</p>
                <p className="text-slate-300">samples: {champion.training_samples}</p>
                <p className="text-slate-300">model: {champion.model_type}</p>
                <p className="text-slate-400 text-xs break-all">{champion.model_artifact_path}</p>
                <ChampionMetricsTable champion={champion} />
              </div>
            )}
          </AsyncSectionShell>
          <div className="mt-3 flex gap-2">
            <button
              className="btn btn-primary text-xs"
              onClick={() => retrainMutation.mutate({ force: true, triggered_by: 'frontend' })}
              disabled={retrainMutation.isPending}
            >
              Retrain
            </button>
            <button
              className="btn btn-secondary text-xs"
              onClick={() => rollbackMutation.mutate()}
              disabled={rollbackMutation.isPending}
            >
              Rollback
            </button>
          </div>
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">Drift Status</h2>
          <AsyncSectionShell
            loading={driftLoading}
            error={driftError}
            empty={!drift && 'No drift data.'}
            minHeight="min-h-[80px]"
          >
            {drift && (
              <div className="space-y-2 text-sm">
                {drift.checked_at && (
                  <p className="text-slate-400 text-xs">
                    Last checked: {new Date(drift.checked_at).toLocaleString()}
                  </p>
                )}
                {drift.new_samples != null && (
                  <p className="text-slate-300">New samples: <span className="text-white">{drift.new_samples}</span></p>
                )}
                <div className="flex items-center gap-2">
                  <span className="text-slate-300">Type:</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] border ${
                    drift.drift_type === 'none'
                      ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
                      : 'bg-amber-500/20 border-amber-500/40 text-amber-300'
                  }`}>
                    {drift.drift_type}
                  </span>
                </div>
                <p className="text-slate-300">Feature drift: <span className="text-white">{drift.feature_drift_fraction}</span></p>
                <p className="text-slate-300">RMSE drift: <span className="text-white">{drift.rmse_drift_pct}%</span></p>
                <p className="text-slate-300">Page-Hinkley: <span className="text-white">{String(drift.page_hinkley_detected)}</span></p>
                <div className="flex items-center gap-2">
                  <span className="text-slate-300">Should retrain:</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] border ${
                    drift.should_retrain
                      ? 'bg-red-500/20 border-red-500/40 text-red-300'
                      : 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
                  }`}>
                    {drift.should_retrain ? 'Yes' : 'No'}
                  </span>
                </div>
                {drift.drifted_targets?.length > 0 && (
                  <div className="mt-2 border-t border-slate-700 pt-2">
                    <p className="text-slate-400 text-xs font-medium mb-1">Drifted Targets</p>
                    <div className="flex flex-wrap gap-1">
                      {drift.drifted_targets.map((t) => (
                        <span
                          key={t}
                          className="px-1.5 py-0.5 rounded text-[10px] bg-red-500/20 border border-red-500/40 text-red-300"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </AsyncSectionShell>
        </div>
      </div>

      <DiagnosticsSection />

      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-300">Model History</h2>
          <div className="flex gap-2">
            <input
              type="number"
              className="input py-1 px-2 text-xs w-20"
              value={historyLimit}
              min="1"
              max="200"
              onChange={(e) => setHistoryLimit(e.target.value)}
            />
            <select
              className="input py-1 px-2 text-xs"
              value={historyStatus}
              onChange={(e) => setHistoryStatus(e.target.value)}
            >
              <option value="">All</option>
              <option value="promoted">Promoted</option>
              <option value="challenger">Challenger</option>
              <option value="archived">Archived</option>
            </select>
          </div>
        </div>

        <AsyncSectionShell
          loading={historyLoading}
          error={historyError}
          empty={history.length === 0 && 'No model history.'}
          minHeight="min-h-[200px]"
        >
          <div className="max-h-[360px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-400 text-center border-b border-slate-700">
                  <th className="py-2">Version</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Samples</th>
                  <th className="py-2">Created</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {history.map((m) => (
                  <tr key={m.version_id} className="border-b border-slate-800 text-slate-300 text-center">
                    <td className="py-2 font-mono">{m.version_id}</td>
                    <td className="py-2">{m.status}</td>
                    <td className="py-2">{m.training_samples}</td>
                    <td className="py-2">{m.created_at || '-'}</td>
                    <td className="py-2">
                      <div className="flex justify-center">
                        <button
                          className="btn btn-secondary text-xs"
                          onClick={() => promoteMutation.mutate(m.version_id)}
                          disabled={promoteMutation.isPending}
                        >
                          Promote
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </AsyncSectionShell>
      </div>
    </div>
  )
}

export default MLOps
