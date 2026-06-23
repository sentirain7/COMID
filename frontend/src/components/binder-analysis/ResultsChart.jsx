import { useEffect, useMemo, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

const CRYSTAL_COLORS = [
  '#60a5fa', '#34d399', '#fbbf24', '#f87171', '#a78bfa',
  '#fb923c', '#2dd4bf', '#e879f9',
]

function ResultsChart({ results = [] }) {
  const metricKeys = useMemo(() => {
    const keys = new Set()
    for (const r of results) {
      for (const k of Object.keys(r.metrics || {})) {
        keys.add(k)
      }
    }
    return Array.from(keys)
  }, [results])

  const [selectedMetric, setSelectedMetric] = useState('')

  useEffect(() => {
    if (metricKeys.length > 0 && !metricKeys.includes(selectedMetric)) {
      setSelectedMetric(metricKeys[0])
    }
  }, [selectedMetric, metricKeys])

  const { chartData, crystalMaterials } = useMemo(() => {
    const materials = new Set()
    const byTemp = {}
    for (const r of results) {
      const temp = r.temperature_K
      if (temp == null) continue
      const crystal = r.crystal_material || 'bulk'
      materials.add(crystal)
      const val = r.metrics?.[selectedMetric]?.value
      if (val == null) continue
      if (!byTemp[temp]) byTemp[temp] = { temperature_K: temp }
      byTemp[temp][crystal] = val
    }
    return {
      chartData: Object.values(byTemp).sort((a, b) => a.temperature_K - b.temperature_K),
      crystalMaterials: Array.from(materials),
    }
  }, [results, selectedMetric])

  if (metricKeys.length === 0) {
    return <p className="text-sm text-slate-400">No metric data available.</p>
  }

  const unit = results.find((r) => r.metrics?.[selectedMetric]?.unit)?.metrics?.[selectedMetric]?.unit || ''

  return (
    <div>
      <div className="mb-3">
        <select
          className="input py-1 text-xs"
          value={selectedMetric}
          onChange={(e) => setSelectedMetric(e.target.value)}
        >
          {metricKeys.map((key) => (
            <option key={key} value={key}>{key}{unit ? ` (${unit})` : ''}</option>
          ))}
        </select>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="temperature_K"
              stroke="#94a3b8"
              tick={{ fontSize: 11 }}
              label={{ value: 'Temperature (K)', position: 'insideBottom', offset: -2, fontSize: 11, fill: '#94a3b8' }}
            />
            <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {crystalMaterials.map((mat, i) => (
              <Line
                key={mat}
                type="monotone"
                dataKey={mat}
                stroke={CRYSTAL_COLORS[i % CRYSTAL_COLORS.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
                name={mat}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default ResultsChart
