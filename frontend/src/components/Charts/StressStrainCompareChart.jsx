import { useMemo } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'

const SERIES_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#a855f7', '#14b8a6', '#f472b6', '#84cc16']

/**
 * Per-candidate stress-strain curve comparison (wizard ④, plan §8).
 *
 * series: [{ label, strain: number[], stress: number[] }]
 * (mapped from columns.strain/columns.stress of the array-metric-compare response)
 */
export default function StressStrainCompareChart({ series }) {
  const { data, labels } = useMemo(() => {
    const valid = (series || []).filter((s) => s?.strain?.length && s?.stress?.length)
    if (!valid.length) return { data: [], labels: [] }
    // Each curve may have a different strain grid, so merge per-series
    // (strain, value) points by strain key (recharts treats missing keys as
    // broken lines).
    const byStrain = new Map()
    valid.forEach((s, si) => {
      s.strain.forEach((x, i) => {
        const key = Number(x.toFixed(6))
        if (!byStrain.has(key)) byStrain.set(key, { strain: key })
        byStrain.get(key)[`s${si}`] = s.stress[i]
      })
    })
    return {
      data: Array.from(byStrain.values()).sort((a, b) => a.strain - b.strain),
      labels: valid.map((s) => s.label),
    }
  }, [series])

  if (!data.length) {
    return (
      <div className="text-xs text-slate-500 p-4 text-center">
        No stress-strain curves to compare
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="strain"
          type="number"
          tickFormatter={(v) => v.toFixed(2)}
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
          label={{ value: 'Strain', position: 'insideBottomRight', offset: -4, fontSize: 11, fill: '#94a3b8' }}
        />
        <YAxis
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
          label={{ value: 'Stress (MPa)', angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#94a3b8' }}
        />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
          labelFormatter={(v) => `Strain: ${Number(v).toFixed(4)}`}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {labels.map((label, i) => (
          <Line
            key={label}
            type="monotone"
            dataKey={`s${i}`}
            name={label}
            stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
