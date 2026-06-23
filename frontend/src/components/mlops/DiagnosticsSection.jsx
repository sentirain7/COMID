import { useState } from 'react'
import {
  useDataCoverage,
  useDataQuality,
  useFeatureImportance,
  useLearningCurve,
  useParityPlot,
  useResiduals,
  useStructuralMLStatus,
} from '../../hooks/useApi'
import {
  getVisibleEIntraMethodDisplay,
} from '../../lib/eIntraMethod'
import ParityPlot from '../Charts/ParityPlot'
import FeatureImportanceChart from '../Charts/FeatureImportanceChart'
import ResidualHistogram from '../Charts/ResidualHistogram'
import LearningCurve from '../Charts/LearningCurve'
import { AsyncSectionShell } from '../shared'
import StructuralEvalPanel from './StructuralEvalPanel'
import { TARGET_OPTIONS } from './helpers'

const formatMethodLabel = (value) => {
  if (!value) return null
  return getVisibleEIntraMethodDisplay(value).label
}

function DiagnosticsSection() {
  const [diagTarget, setDiagTarget] = useState('density')

  const { data: structStatus } = useStructuralMLStatus()
  const championTargets = new Set(structStatus?.champion_supported_targets || [])

  const { data: parityData, loading: parityLoading, error: parityError } = useParityPlot(diagTarget)
  const { data: fiData, loading: fiLoading, error: fiError } = useFeatureImportance(diagTarget)
  const { data: residData, loading: residLoading, error: residError } = useResiduals(diagTarget)
  const { data: lcData, loading: lcLoading, error: lcError } = useLearningCurve(diagTarget)
  const { data: coverageData, loading: coverageLoading, error: coverageError } = useDataCoverage()
  const { data: qualityData, loading: qualityLoading, error: qualityError } = useDataQuality()
  const championMethod = coverageData?.champion_e_intra_method || coverageData?.e_intra_method || null
  const submissionMethod = coverageData?.submission_default_e_intra_method || null
  const methodMismatch = coverageData?.e_intra_method_mismatch
  const hasMismatchSignal = typeof methodMismatch === 'boolean'

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-slate-300">Model Diagnostics</h2>
        <select
          className="input py-1 px-2 text-xs"
          value={diagTarget}
          onChange={(e) => setDiagTarget(e.target.value)}
        >
          {TARGET_OPTIONS.map((t) => (
            <option key={t} value={t}>
              {championTargets.has(t) ? `★ ${t}` : t}
            </option>
          ))}
        </select>
      </div>

      {/* V7 structural ML opt-in status + champion supported targets (user request) */}
      {structStatus && (
        <div className="flex flex-wrap items-center gap-2 mb-4 text-[10px]">
          <span
            className={`px-1.5 py-0.5 rounded border ${
              structStatus.enabled
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                : 'bg-slate-700/60 border-slate-600 text-slate-300'
            }`}
            title="Structural (V7) ML real-time retrain opt-in policy (default OFF)"
          >
            Structural retrain: {structStatus.enabled ? 'ON' : 'OFF (opt-in)'}
          </span>
          {structStatus.champion_feature_set && (
            <span
              className={`px-1.5 py-0.5 rounded border ${
                structStatus.champion_feature_set === 'v7'
                  ? 'bg-blue-500/10 border-blue-500/40 text-blue-300'
                  : 'bg-slate-700/60 border-slate-600 text-slate-300'
              }`}
              title="Feature set of the current champion model"
            >
              Champion: {structStatus.champion_feature_set}
            </span>
          )}
          {structStatus.champion_supported_targets?.length > 0 && (
            <span className="text-slate-400">
              Supported properties: {structStatus.champion_supported_targets.join(', ')}
            </span>
          )}
          {structStatus.champion_model_types &&
            Object.keys(structStatus.champion_model_types).length > 0 && (
              <span
                className="text-slate-400"
                title="Per-property XGBoost-vs-RandomForest competition winner (champion)"
              >
                Model:{' '}
                {Object.entries(structStatus.champion_model_types)
                  .map(([t, m]) => `${t}=${m === 'random_forest' ? 'RF' : 'XGB'}`)
                  .join(', ')}
              </span>
            )}
          {structStatus.force_fields?.length > 0 && (
            <span className="text-slate-500">FF: {structStatus.force_fields.join('/')}</span>
          )}
        </div>
      )}

      {/* V7 on-demand: XGBoost vs RandomForest competition eval + challenger training (dry-run) */}
      <StructuralEvalPanel target={diagTarget} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <h3 className="text-xs font-medium text-slate-400 mb-2">Parity Plot</h3>
          <ParityPlot data={parityData} loading={parityLoading} error={parityError} />
        </div>
        <div>
          <h3 className="text-xs font-medium text-slate-400 mb-2">Feature Importance</h3>
          <FeatureImportanceChart data={fiData} loading={fiLoading} error={fiError} />
        </div>
        <div>
          <h3 className="text-xs font-medium text-slate-400 mb-2">Residual Distribution</h3>
          <ResidualHistogram data={residData} loading={residLoading} error={residError} />
        </div>
        <div>
          <h3 className="text-xs font-medium text-slate-400 mb-2">Learning Curve</h3>
          <LearningCurve data={lcData} loading={lcLoading} error={lcError} />
        </div>
      </div>

      {/* PR 2 (Codex Round 9): Data Coverage panel — surface
          coverage strict-resolver errors and the resolved E_intra method
          contract.  When the backend's strict resolver raises (registry
          outage), the user sees the error inline instead of an empty
          panel that silently looked like a "no data" baseline. */}
      <AsyncSectionShell
        loading={coverageLoading}
        error={coverageError && `Data coverage failed: ${coverageError}`}
        empty={!coverageData && !coverageLoading && !coverageError && 'No coverage data.'}
        minHeight="min-h-[60px]"
      >
        {coverageData && (
          <div className="mt-4 border-t border-slate-700 pt-3">
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <h3 className="text-xs font-medium text-slate-400">Data Coverage</h3>
              {championMethod && (
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] border bg-blue-500/10 border-blue-500/40 text-blue-300"
                  title={`Champion / serving method${coverageData.method_resolution_status ? ` • resolved via ${coverageData.method_resolution_status}` : ''}`}
                >
                  Champion: {formatMethodLabel(championMethod)}
                </span>
              )}
              {submissionMethod && (
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] border bg-slate-700/60 border-slate-600 text-slate-200"
                >
                  Submit default: {formatMethodLabel(submissionMethod)}
                </span>
              )}
              {hasMismatchSignal && (
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] border ${
                    methodMismatch
                      ? 'bg-amber-500/10 border-amber-500/40 text-amber-300'
                      : 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                  }`}
                  title="Compares champion serving method against the default used to seed new submissions"
                >
                  {methodMismatch ? 'Method mismatch' : 'Methods aligned'}
                </span>
              )}
              {coverageData.method_resolution_status && (
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] border bg-slate-800/80 border-slate-600 text-slate-400"
                  title="Backend method-resolution status"
                >
                  {coverageData.method_resolution_status}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              <div className="bg-slate-800 rounded p-2">
                <p className="text-slate-400">Total Experiments</p>
                <p className="text-white font-mono">{coverageData.total_experiments}</p>
              </div>
              {Object.entries(coverageData.per_target || {}).slice(0, 3).map(([target, info]) => (
                <div key={target} className="bg-slate-800 rounded p-2">
                  <p className="text-slate-400 truncate" title={target}>{target}</p>
                  <p className="text-white font-mono">
                    {info.samples}
                    <span className={`ml-1 text-[10px] ${info.sufficient ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {info.sufficient ? 'OK' : 'Low'}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </AsyncSectionShell>

      <div className="mt-4 border-t border-slate-700 pt-3">
        <AsyncSectionShell
          loading={qualityLoading}
          error={qualityError && `Data quality check failed: ${qualityError}`}
          empty={qualityData?.issues?.length === 0 && 'No data quality issues found.'}
          minHeight="min-h-[60px]"
        >
          {qualityData?.issues?.length > 0 && (
            <>
              <h3 className="text-xs font-medium text-slate-400 mb-2">
                Data Quality Issues
                <span className="ml-1 text-amber-400">({qualityData.issues.length})</span>
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mb-2">
                {Object.entries(qualityData.summary || {}).map(([type, count]) => (
                  <div key={type} className="bg-slate-800 rounded p-2">
                    <p className="text-slate-400 truncate" title={type}>{type}</p>
                    <p className="text-amber-300 font-mono">{count}</p>
                  </div>
                ))}
              </div>
              <div className="max-h-40 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-400 text-left border-b border-slate-700">
                      <th className="py-1 pr-2">Type</th>
                      <th className="py-1 pr-2">Experiment</th>
                      <th className="py-1">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {qualityData.issues.slice(0, 20).map((issue, i) => (
                      <tr key={i} className="border-b border-slate-800 text-slate-300">
                        <td className="py-1 pr-2 font-mono">{issue.issue_type}</td>
                        <td className="py-1 pr-2 font-mono">{issue.exp_id}</td>
                        <td className="py-1 text-slate-400 truncate max-w-[200px]" title={JSON.stringify(issue.details)}>
                          {JSON.stringify(issue.details)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {qualityData.issues.length > 20 && (
                  <p className="text-slate-500 text-xs mt-1">... and {qualityData.issues.length - 20} more</p>
                )}
              </div>
            </>
          )}
        </AsyncSectionShell>
      </div>
    </div>
  )
}

export default DiagnosticsSection
