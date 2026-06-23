import { useMemo, useState } from 'react'
import { parseMetricsJson } from './helpers'
import MetricStatusBadge from './MetricStatusBadge'

function ChampionMetricsTable({ champion }) {
  const [expanded, setExpanded] = useState(false)

  const metricsData = useMemo(() => {
    return parseMetricsJson(champion?.test_metrics_json) || parseMetricsJson(champion?.val_metrics_json)
  }, [champion])

  if (!metricsData) return null

  const rows = Object.entries(metricsData).map(([target, m]) => ({
    target,
    rmse: m?.rmse ?? m?.RMSE ?? null,
    r2: m?.r2 ?? m?.R2 ?? m?.r_squared ?? null,
  }))

  if (rows.length === 0) return null

  return (
    <div className="mt-3 border-t border-slate-700 pt-3">
      <button
        type="button"
        className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        onClick={() => setExpanded((prev) => !prev)}
      >
        <span className="font-medium">Per-Target Metrics</span>
        <span className="text-slate-500">({rows.length})</span>
        <span className="ml-1">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>
      {expanded && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-400 text-center border-b border-slate-700">
                <th className="py-1.5 pr-3">Target</th>
                <th className="py-1.5 pr-3">RMSE</th>
                <th className="py-1.5 pr-3">R²</th>
                <th className="py-1.5">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ target, rmse, r2 }) => (
                <tr key={target} className="border-b border-slate-800 text-slate-300 text-center">
                  <td className="py-1.5 pr-3 font-mono">{target}</td>
                  <td className="py-1.5 pr-3 tabular-nums">
                    {rmse != null ? rmse.toFixed(4) : '-'}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">
                    {r2 != null ? r2.toFixed(4) : '-'}
                  </td>
                  <td className="py-1.5">
                    <div className="flex justify-center">
                      <MetricStatusBadge r2={r2} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default ChampionMetricsTable
