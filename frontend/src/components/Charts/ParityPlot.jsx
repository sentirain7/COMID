import { useMemo } from 'react'

// Colors per data split (distinguishing train vs validation/test — user request).
const SPLIT_STYLE = {
  train: { color: '#34d399', label: 'Train' }, // emerald
  validation: { color: '#f59e0b', label: 'Validation' }, // amber
  test: { color: '#60a5fa', label: 'Test/Holdout' }, // blue
  unknown: { color: '#94a3b8', label: 'Unlabeled' }, // slate
}

/**
 * Parity plot: predicted vs actual values with identity line.
 *
 * Points are colored by data split (train/validation/test) so that predictions
 * for training data and validation data are shown in different colors. When the
 * backend response has no split labels (legacy), falls back to residual-sign coloring.
 */
export default function ParityPlot({ data, loading, error }) {
  const { points, metrics, trainMetrics, bounds, splitsPresent } = useMemo(() => {
    if (!data?.points?.length) {
      return { points: [], metrics: null, trainMetrics: null, bounds: null, splitsPresent: [] }
    }

    const pts = data.points
    const allVals = pts.flatMap((p) => [p.actual, p.predicted])
    const min = Math.min(...allVals)
    const max = Math.max(...allVals)
    const pad = (max - min) * 0.05 || 0.01
    const present = [...new Set(pts.map((p) => p.split).filter(Boolean))]

    return {
      points: pts,
      metrics: data.metrics,
      trainMetrics: data.train_metrics || null,
      bounds: { min: min - pad, max: max + pad, range: max - min + 2 * pad },
      splitsPresent: present,
    }
  }, [data])

  if (loading) return <p className="text-slate-400 text-sm">Loading parity plot...</p>
  if (error) return <p className="text-amber-300 text-sm">{error}</p>
  if (!points.length) return <p className="text-slate-400 text-sm">No data for parity plot.</p>

  const W = 320
  const H = 320
  const M = { top: 20, right: 20, bottom: 40, left: 50 }
  const plotW = W - M.left - M.right
  const plotH = H - M.top - M.bottom

  const scale = (v) => (v - bounds.min) / bounds.range
  const maxAbsResidual = Math.max(...points.map((p) => Math.abs(p.residual)), 1e-9)
  const useSplitColor = splitsPresent.length > 0

  const pointColor = (p) => {
    if (useSplitColor) {
      return (SPLIT_STYLE[p.split] || SPLIT_STYLE.unknown).color
    }
    // Legacy (no split info): residual-sign color
    const intensity = Math.min(Math.abs(p.residual) / maxAbsResidual, 1)
    return p.residual > 0
      ? `rgba(59,130,246,${0.3 + intensity * 0.7})`
      : `rgba(239,68,68,${0.3 + intensity * 0.7})`
  }

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-sm">
        <g transform={`translate(${M.left},${M.top})`}>
          {/* Identity line */}
          <line
            x1={0} y1={plotH}
            x2={plotW} y2={0}
            stroke="#64748b" strokeWidth="1" strokeDasharray="4,3"
          />
          {/* Points */}
          {points.map((p, i) => {
            const x = scale(p.actual) * plotW
            const y = (1 - scale(p.predicted)) * plotH
            const splitLabel = (SPLIT_STYLE[p.split] || SPLIT_STYLE.unknown).label
            return (
              <circle key={i} cx={x} cy={y} r={3} fill={pointColor(p)} fillOpacity={0.8} stroke="none">
                <title>{`${p.exp_id}\nSplit: ${splitLabel}\nActual: ${p.actual.toFixed(4)}\nPredicted: ${p.predicted.toFixed(4)}\nResidual: ${p.residual.toFixed(4)}`}</title>
              </circle>
            )
          })}
          {/* Axes labels */}
          <text x={plotW / 2} y={plotH + 30} textAnchor="middle" className="fill-slate-400" style={{ fontSize: 10 }}>
            Actual
          </text>
          <text x={-plotH / 2} y={-35} textAnchor="middle" transform="rotate(-90)" className="fill-slate-400" style={{ fontSize: 10 }}>
            Predicted
          </text>
        </g>
      </svg>

      {/* Split legend (train/validation color legend) */}
      {useSplitColor && (
        <div className="flex gap-3 text-[10px] text-slate-300 mt-1 justify-center flex-wrap">
          {splitsPresent.map((s) => (
            <span key={s} className="flex items-center gap-1">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{ backgroundColor: (SPLIT_STYLE[s] || SPLIT_STYLE.unknown).color }}
              />
              {(SPLIT_STYLE[s] || SPLIT_STYLE.unknown).label}
            </span>
          ))}
        </div>
      )}

      {/* Metrics: holdout + (if present) train shown separately */}
      {metrics && (
        <div className="flex flex-col items-center text-xs text-slate-300 mt-1 gap-0.5">
          <div className="flex gap-3">
            <span className="text-blue-300">Holdout</span>
            <span>RMSE: {metrics.rmse?.toFixed(4)}</span>
            <span>R²: {metrics.r2?.toFixed(4)}</span>
            <span>n={metrics.n_points}</span>
          </div>
          {trainMetrics && (
            <div className="flex gap-3 text-emerald-300/80">
              <span className="text-emerald-300">Train</span>
              <span>RMSE: {trainMetrics.rmse?.toFixed(4)}</span>
              <span>R²: {trainMetrics.r2?.toFixed(4)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
