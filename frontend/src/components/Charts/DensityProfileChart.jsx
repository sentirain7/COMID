import { useMemo } from 'react'
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import { getChartColorByIndex } from '../../lib/chartUtils'

/**
 * Density profile chart — multi-experiment overlay (AreaChart).
 *
 * Props:
 *   experiments: [{ expId, label, columns: { z, density }, metadata }]
 */
export default function DensityProfileChart({ experiments = [] }) {
  const { data, keys } = useMemo(() => {
    if (!experiments.length) return { data: [], keys: [] }

    const baseZ = experiments[0]?.columns?.z || []
    if (!baseZ.length) return { data: [], keys: [] }

    const merged = baseZ.map((z) => ({ z }))
    const seriesKeys = []

    experiments.forEach((exp, i) => {
      const z = exp.columns?.z || []
      const density = exp.columns?.density || []
      const key = `density_${i}`
      seriesKeys.push({ key, label: exp.label || exp.expId, index: i })

      if (z.length === baseZ.length) {
        density.forEach((val, j) => {
          merged[j][key] = val
        })
      } else {
        let zi = 0
        merged.forEach((row) => {
          while (zi < z.length - 1 && Math.abs(z[zi + 1] - row.z) < Math.abs(z[zi] - row.z)) {
            zi++
          }
          row[key] = zi < density.length ? density[zi] : null
        })
      }
    })

    return { data: merged, keys: seriesKeys }
  }, [experiments])

  if (!data.length) {
    return (
      <div className="text-xs text-slate-500 p-4 text-center">
        No density profile data available
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={320}>
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="z"
          type="number"
          tickFormatter={(v) => v.toFixed(0)}
          label={{ value: 'z (\u00C5)', position: 'insideBottomRight', offset: -4, fontSize: 11, fill: '#94a3b8' }}
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
        />
        <YAxis
          label={{ value: 'Density (g/cm\u00B3)', angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#94a3b8' }}
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
        />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
          labelFormatter={(v) => `z = ${Number(v).toFixed(1)} \u00C5`}
          formatter={(v, name) => {
            const entry = keys.find((k) => k.key === name)
            return [`${Number(v).toFixed(4)} g/cm\u00B3`, entry?.label || name]
          }}
        />
        {keys.length > 1 && (
          <Legend
            wrapperStyle={{ fontSize: 11, color: '#94a3b8' }}
            formatter={(value) => {
              const entry = keys.find((k) => k.key === value)
              return entry?.label || value
            }}
          />
        )}

        {keys.map(({ key, index }) => {
          const color = getChartColorByIndex(index)
          return (
            <Area
              key={key}
              type="monotone"
              dataKey={key}
              stroke={color}
              fill={color}
              fillOpacity={0.15}
              strokeWidth={1.5}
              connectNulls
            />
          )
        })}
      </AreaChart>
    </ResponsiveContainer>
  )
}
