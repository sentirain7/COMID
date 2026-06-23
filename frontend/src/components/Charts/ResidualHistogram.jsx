import { useMemo } from 'react'

/**
 * Histogram of prediction residuals with summary statistics.
 */
export default function ResidualHistogram({ data, loading, error }) {
  const { bins, stats } = useMemo(() => {
    if (!data?.residuals?.length) return { bins: [], stats: null }

    const residuals = data.residuals
    const n = residuals.length
    const nBins = Math.min(Math.max(Math.ceil(Math.sqrt(n)), 5), 30)
    const min = Math.min(...residuals)
    const max = Math.max(...residuals)
    const range = max - min || 1e-9
    const binWidth = range / nBins

    const counts = new Array(nBins).fill(0)
    for (const r of residuals) {
      const idx = Math.min(Math.floor((r - min) / binWidth), nBins - 1)
      counts[idx]++
    }

    const maxCount = Math.max(...counts, 1)
    const binsData = counts.map((c, i) => ({
      x0: min + i * binWidth,
      x1: min + (i + 1) * binWidth,
      count: c,
      height: c / maxCount,
    }))

    return { bins: binsData, stats: data.stats }
  }, [data])

  if (loading) return <p className="text-slate-400 text-sm">Loading residuals...</p>
  if (error) return <p className="text-amber-300 text-sm">{error}</p>
  if (!bins.length) return <p className="text-slate-400 text-sm">No residual data.</p>

  const W = 320
  const H = 180
  const M = { top: 10, right: 10, bottom: 30, left: 10 }
  const plotW = W - M.left - M.right
  const plotH = H - M.top - M.bottom
  const barW = plotW / bins.length

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-sm">
        <g transform={`translate(${M.left},${M.top})`}>
          {bins.map((b, i) => (
            <rect
              key={i}
              x={i * barW + 1}
              y={plotH * (1 - b.height)}
              width={Math.max(barW - 2, 1)}
              height={plotH * b.height}
              fill="rgba(59,130,246,0.6)"
              rx={1}
            >
              <title>{`[${b.x0.toFixed(4)}, ${b.x1.toFixed(4)}): ${b.count}`}</title>
            </rect>
          ))}
          {/* Zero line */}
          {bins.length > 0 && (() => {
            const allMin = bins[0].x0
            const allMax = bins[bins.length - 1].x1
            const range = allMax - allMin || 1
            const zeroX = ((0 - allMin) / range) * plotW
            if (zeroX >= 0 && zeroX <= plotW) {
              return (
                <line
                  x1={zeroX} y1={0} x2={zeroX} y2={plotH}
                  stroke="#ef4444" strokeWidth="1" strokeDasharray="3,2"
                />
              )
            }
            return null
          })()}
          <text x={plotW / 2} y={plotH + 20} textAnchor="middle" className="fill-slate-400" style={{ fontSize: 10 }}>
            Residual (actual - predicted)
          </text>
        </g>
      </svg>
      {stats && (
        <div className="flex gap-3 text-xs text-slate-300 mt-1 justify-center">
          <span>mean: {stats.mean?.toFixed(4)}</span>
          <span>std: {stats.std?.toFixed(4)}</span>
          <span>skew: {stats.skew?.toFixed(3)}</span>
          <span>n={stats.count}</span>
        </div>
      )}
    </div>
  )
}
