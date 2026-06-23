import { useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts'
import { Download } from 'lucide-react'
import { THERMO_COLORS } from '../../lib/constants'
import { exportChartToCSV } from '../../lib/csvExport'

const Y_AXIS_OPTIONS = [
  { key: 'temp', label: 'Temperature (K)', color: THERMO_COLORS?.temperature || '#ef4444' },
  { key: 'press', label: 'Pressure (atm)', color: THERMO_COLORS?.pressure || '#3b82f6' },
  { key: 'density', label: 'Density (g/cm\u00B3)', color: THERMO_COLORS?.density || '#10b981' },
  { key: 'pe', label: 'PE (kcal/mol)', color: '#f59e0b' },
  { key: 'ke', label: 'KE (kcal/mol)', color: '#8b5cf6' },
  { key: 'vol', label: 'Volume (\u00C5\u00B3)', color: THERMO_COLORS?.volume || '#06b6d4' },
]

/**
 * Thermo log chart — single experiment, Y-axis metric dropdown.
 *
 * Props:
 *   experiments: [{ expId, label, columns: { step, time_ps, temp, press, pe, ke, vol, density } }]
 *     (Only first experiment used — thermo_log is single-experiment only)
 */
export default function ThermoLogChart({ experiments = [] }) {
  const [activeY, setActiveY] = useState('temp')

  const exp = experiments[0]

  const data = useMemo(() => {
    const columns = exp?.columns || {}
    const time = columns.time_ps || []
    const yValues = columns[activeY] || []
    if (!time.length || !yValues.length) return []

    const n = Math.min(time.length, yValues.length)
    return Array.from({ length: n }, (_, i) => ({
      time_ps: time[i],
      value: yValues[i],
    }))
  }, [exp, activeY])

  const yConfig = Y_AXIS_OPTIONS.find((o) => o.key === activeY) || Y_AXIS_OPTIONS[0]

  if (!exp) {
    return (
      <div className="text-xs text-slate-500 p-4 text-center">
        Select an experiment to view thermo log data
      </div>
    )
  }

  if (!data.length) {
    return (
      <div className="text-xs text-slate-500 p-4 text-center">
        No thermo log data available for this experiment
      </div>
    )
  }

  // Format time for tooltip
  const formatTime = (t) => {
    if (t >= 1000) return `${(t / 1000).toFixed(2)} ns`
    return `${t.toFixed(1)} ps`
  }

  const handleExportCSV = () => {
    if (!data.length) return
    const filename = `thermo_log_${exp.expId || exp.label}_${activeY}`
    exportChartToCSV(data, ['time_ps', 'value'], filename, {
      time_ps: 'Time (ps)',
      value: yConfig.label,
    })
  }

  return (
    <div className="h-full flex flex-col">
      {/* Y-axis selector + export */}
      <div className="flex gap-1 mb-3 flex-wrap flex-shrink-0 items-center">
        {Y_AXIS_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => setActiveY(opt.key)}
            className={`px-2 py-1 text-xs rounded border transition-colors ${
              activeY === opt.key
                ? 'border-blue-400/40 text-blue-300'
                : 'border-slate-600 text-slate-400 hover:text-slate-300'
            }`}
            style={activeY === opt.key ? { backgroundColor: `${opt.color}20` } : { backgroundColor: '#1e293b' }}
          >
            {opt.label.split(' (')[0]}
          </button>
        ))}
        <button
          onClick={handleExportCSV}
          className="ml-auto px-2 py-1 text-xs rounded border bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300 flex items-center gap-1"
          title="Export to CSV"
        >
          <Download className="w-3 h-3" />
          CSV
        </button>
      </div>

      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="time_ps"
              type="number"
              tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}ns` : `${v.toFixed(0)}ps`)}
              label={{ value: 'Time', position: 'insideBottomRight', offset: -4, fontSize: 11, fill: '#94a3b8' }}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              stroke="#475569"
            />
            <YAxis
              label={{ value: yConfig.label, angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#94a3b8' }}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              stroke="#475569"
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
              labelFormatter={(v) => `t = ${formatTime(Number(v))}`}
              formatter={(v) => [`${Number(v).toFixed(4)}`, yConfig.label]}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={yConfig.color}
              strokeWidth={1.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Info */}
      <div className="mt-1 text-xs text-slate-500 px-2 flex-shrink-0">
        {exp.label} — {data.length} data points
      </div>
    </div>
  )
}
