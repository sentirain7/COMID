import { useMemo } from 'react'

/**
 * Learning curve: training samples vs RMSE (train/val/test lines).
 */
export default function LearningCurve({ data, loading, error }) {
  const { points, bounds } = useMemo(() => {
    if (!data?.points?.length) return { points: [], bounds: null }

    const pts = data.points
    const allRmse = pts.flatMap((p) => [p.train_rmse, p.val_rmse, p.test_rmse].filter(Boolean))
    const allSamples = pts.map((p) => p.training_samples)
    const minR = Math.min(...allRmse)
    const maxR = Math.max(...allRmse)
    const minS = Math.min(...allSamples)
    const maxS = Math.max(...allSamples)
    const padR = (maxR - minR) * 0.1 || 0.01
    const padS = (maxS - minS) * 0.05 || 1

    return {
      points: pts,
      bounds: {
        minR: Math.max(0, minR - padR),
        maxR: maxR + padR,
        minS: Math.max(0, minS - padS),
        maxS: maxS + padS,
      },
    }
  }, [data])

  if (loading) return <p className="text-slate-400 text-sm">Loading learning curve...</p>
  if (error) return <p className="text-amber-300 text-sm">{error}</p>
  if (!points.length) return <p className="text-slate-400 text-sm">No learning curve data.</p>

  const W = 360
  const H = 200
  const M = { top: 20, right: 20, bottom: 40, left: 50 }
  const plotW = W - M.left - M.right
  const plotH = H - M.top - M.bottom

  const scaleX = (s) => ((s - bounds.minS) / (bounds.maxS - bounds.minS)) * plotW
  const scaleY = (r) => (1 - (r - bounds.minR) / (bounds.maxR - bounds.minR)) * plotH

  const makePath = (key) => {
    return points
      .filter((p) => p[key] != null)
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${scaleX(p.training_samples)},${scaleY(p[key])}`)
      .join(' ')
  }

  const series = [
    { key: 'train_rmse', color: '#3b82f6', label: 'Train' },
    { key: 'val_rmse', color: '#f59e0b', label: 'Val' },
    { key: 'test_rmse', color: '#ef4444', label: 'Test' },
  ]

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-md">
        <g transform={`translate(${M.left},${M.top})`}>
          {series.map(({ key, color }) => (
            <path
              key={key}
              d={makePath(key)}
              fill="none"
              stroke={color}
              strokeWidth="1.5"
            />
          ))}
          {/* Data points */}
          {series.map(({ key, color }) =>
            points
              .filter((p) => p[key] != null)
              .map((p, i) => (
                <circle
                  key={`${key}-${i}`}
                  cx={scaleX(p.training_samples)}
                  cy={scaleY(p[key])}
                  r={2.5}
                  fill={color}
                >
                  <title>{`${p.version_id}\nSamples: ${p.training_samples}\n${key}: ${p[key]?.toFixed(4)}`}</title>
                </circle>
              ))
          )}
          <text x={plotW / 2} y={plotH + 30} textAnchor="middle" className="fill-slate-400" style={{ fontSize: 10 }}>
            Training Samples
          </text>
          <text x={-plotH / 2} y={-35} textAnchor="middle" transform="rotate(-90)" className="fill-slate-400" style={{ fontSize: 10 }}>
            RMSE
          </text>
        </g>
      </svg>
      <div className="flex gap-4 justify-center mt-1">
        {series.map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1 text-xs text-slate-300">
            <span className="inline-block w-3 h-0.5" style={{ backgroundColor: color }} />
            {label}
          </div>
        ))}
      </div>
    </div>
  )
}
