import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getChartColorByIndex } from '../../lib/chartUtils'
import { mergeCohesiveEnergyDensityProfileExperiments } from '../../lib/arrayMetricProfiles'

export default function CohesiveEnergyDensityProfileChart({ experiments = [] }) {
  const { data, series } = useMemo(
    () => mergeCohesiveEnergyDensityProfileExperiments(experiments),
    [experiments],
  )

  if (!data.length) {
    return (
      <div className="text-xs text-slate-500 p-4 text-center">
        No cohesive energy density profile data available
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="layer_index"
          type="number"
          allowDecimals={false}
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
          label={{
            value: 'Layer Index',
            position: 'insideBottomRight',
            offset: -4,
            fontSize: 11,
            fill: '#94a3b8',
          }}
        />
        <YAxis
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
          label={{
            value: 'CED (MJ/m³)',
            angle: -90,
            position: 'insideLeft',
            offset: 10,
            fontSize: 11,
            fill: '#94a3b8',
          }}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: 6,
            fontSize: 11,
          }}
          labelFormatter={(value, payload) => {
            const firstPayload = Array.isArray(payload) ? payload[0] : null
            const layerLabel = firstPayload?.payload?.layer_label
            return layerLabel ? `Layer ${value} — ${layerLabel}` : `Layer ${value}`
          }}
          formatter={(value, name) => {
            const entry = series.find((item) => item.key === name)
            return [`${Number(value).toFixed(2)} MJ/m³`, entry?.label || name]
          }}
        />
        {series.length > 1 && (
          <Legend
            wrapperStyle={{ fontSize: 11, color: '#94a3b8' }}
            formatter={(value) => series.find((item) => item.key === value)?.label || value}
          />
        )}
        {series.map(({ key, index }) => (
          <Line
            key={key}
            type="monotone"
            dataKey={key}
            stroke={getChartColorByIndex(index)}
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
