import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getArrayMetricCompare } from '../../api/client'
import { useInversePipelineResults } from '../../hooks/useApiInversePipeline'
import StressStrainCompareChart from '../Charts/StressStrainCompareChart'

function SatisfiedBadge({ satisfied }) {
  if (satisfied === true)
    return <span className="px-1.5 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-300">met</span>
  if (satisfied === false)
    return <span className="px-1.5 py-0.5 rounded text-xs bg-rose-500/20 text-rose-300">missed</span>
  return <span className="px-1.5 py-0.5 rounded text-xs bg-slate-600/40 text-slate-400">pending</span>
}

function formatTargetBound(t) {
  const parts = []
  if (t.target_min != null) parts.push(`≥ ${t.target_min}`)
  if (t.target_max != null) parts.push(`≤ ${t.target_max}`)
  return parts.join(' · ') || t.direction
}

const ER_VERDICT_STYLES = {
  ok: 'bg-emerald-500/20 text-emerald-300',
  warn: 'bg-amber-500/20 text-amber-300',
  fail: 'bg-rose-500/20 text-rose-300',
}

function MoistureErRow({ moistureEr }) {
  if (!moistureEr) return null
  return (
    <div className="flex flex-wrap gap-2 mt-1">
      {Object.entries(moistureEr).map(([metric, er]) => (
        <span
          key={metric}
          className={`px-1.5 py-0.5 rounded text-[10px] ${
            ER_VERDICT_STYLES[er.verdict] || 'bg-slate-600/40 text-slate-300'
          }`}
          title={`dry ${Number(er.dry).toPrecision(4)} / wet ${Number(er.wet).toPrecision(4)}`}
        >
          ER({metric}) {Number(er.er).toFixed(2)} · {er.verdict}
        </span>
      ))}
    </div>
  )
}

function MetricCell({ metric, perTarget }) {
  if (!perTarget || perTarget.value == null)
    return <span className="text-slate-500">—</span>
  const se = metric?.source === 'replicate_ensemble' ? metric?.uncertainty : null
  return (
    <span>
      {Number(perTarget.value).toPrecision(4)}
      {se != null && <span className="text-slate-400"> ± {Number(se).toPrecision(2)}</span>}
      {metric?.source === 'replicate_ensemble' && (
        <span className="text-sky-400 text-[10px] ml-1">SE (n={metric.n_replicates})</span>
      )}
    </span>
  )
}

/**
 * Wizard ④ — target vs actual results (plan §8).
 *
 * Per-candidate per_target achievement table (replica ensemble shown as mean±SE) +
 * interface (tensile) curve comparison (stress_strain_curve, reusing array-metric-compare).
 */
function TargetVsActualPanel({ pipelineId }) {
  const { data, isLoading, error } = useInversePipelineResults(pipelineId)

  const layeredExpIds = useMemo(() => {
    if (!data) return []
    const ids = []
    for (const c of data.candidates || []) {
      for (const e of c.experiments || []) {
        if (e.kind?.includes('layered') && e.status === 'completed') ids.push(e.exp_id)
      }
    }
    return ids
  }, [data])

  const curveQuery = useQuery({
    queryKey: ['inverse-pipeline', pipelineId, 'stress-strain-compare', layeredExpIds],
    queryFn: () => getArrayMetricCompare(layeredExpIds, 'stress_strain_curve'),
    enabled: layeredExpIds.length > 0,
  })

  if (isLoading) return <p className="text-slate-400 text-sm">Loading results…</p>
  if (error) return <p className="text-red-400 text-sm">{String(error.message || error)}</p>
  if (!data) return null

  const targets = data.targets || []
  const candidates = data.candidates || []

  const curveSeries = (curveQuery.data?.experiments || []).map((e) => ({
    label: e.label || e.exp_id,
    strain: e.columns?.strain || [],
    stress: e.columns?.stress || [],
  }))

  return (
    <div className="space-y-4">
      <section className="flex items-center justify-between">
        <h3 className="text-slate-200 font-semibold">Target vs actual</h3>
        <span className="text-slate-400 text-xs">
          {data.completed_experiments}/{data.total_experiments} experiments completed
        </span>
      </section>

      {targets.length === 0 && (
        <p className="text-slate-400 text-sm">
          This pipeline has no stored targets metadata.
        </p>
      )}

      <section className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-slate-400">
            <tr>
              <th className="py-1 px-2 text-left">Candidate</th>
              {targets.map((t) => (
                <th key={t.metric_name} className="py-1 px-2 text-left">
                  {t.metric_name}
                  <div className="text-[10px] font-normal text-slate-500">
                    {formatTargetBound(t)} {t.unit || ''}
                  </div>
                </th>
              ))}
              <th className="py-1 px-2">All targets</th>
            </tr>
          </thead>
          <tbody className="text-slate-300">
            {candidates.map((c) => (
              <tr key={c.candidate_index} className="border-t border-slate-700/50">
                <td className="py-1 px-2 align-top">
                  #{c.candidate_index + 1}
                  <MoistureErRow moistureEr={c.moisture_er} />
                </td>
                {targets.map((t) => (
                  <td key={t.metric_name} className="py-1 px-2">
                    <div className="flex items-center gap-2">
                      <MetricCell
                        metric={c.metrics?.[t.metric_name]}
                        perTarget={c.per_target?.[t.metric_name]}
                      />
                      <SatisfiedBadge satisfied={c.per_target?.[t.metric_name]?.satisfied} />
                    </div>
                  </td>
                ))}
                <td className="py-1 px-2 text-center">
                  <SatisfiedBadge satisfied={c.targets_satisfied} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {layeredExpIds.length > 0 && (
        <section>
          <h4 className="text-slate-300 text-sm font-semibold mb-1">
            Interface tensile curves (stress–strain)
          </h4>
          {curveQuery.isLoading ? (
            <p className="text-slate-400 text-xs">Loading curves…</p>
          ) : (
            <StressStrainCompareChart series={curveSeries} />
          )}
        </section>
      )}
    </div>
  )
}

export default TargetVsActualPanel
