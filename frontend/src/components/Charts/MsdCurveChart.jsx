import { useMemo, useState } from 'react'
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
import { Download } from 'lucide-react'
import { getChartColorByIndex } from '../../lib/chartUtils'
import { exportMultiSeriesToCSV } from '../../lib/csvExport'

/**
 * MSD curve chart — multi-experiment overlay with log-log toggle.
 *
 * Props:
 *   experiments: [{ expId, label, columns: { time_ps, msd }, metadata }]
 */
export default function MsdCurveChart({ experiments = [] }) {
  const [logScale, setLogScale] = useState(false)

  const { data, keys } = useMemo(() => {
    if (!experiments.length) return { data: [], keys: [] }

    const baseTime = experiments[0]?.columns?.time_ps || []
    if (!baseTime.length) return { data: [], keys: [] }

    const merged = baseTime.map((t) => ({ time_ps: t }))
    const seriesKeys = []

    experiments.forEach((exp, i) => {
      const t = exp.columns?.time_ps || []
      const msd = exp.columns?.msd || []
      const key = `msd_${i}`
      seriesKeys.push({ key, label: exp.label || exp.expId, index: i, metadata: exp.metadata })

      if (t.length === baseTime.length) {
        msd.forEach((val, j) => {
          merged[j][key] = val
        })
      } else {
        let ti = 0
        merged.forEach((row) => {
          while (ti < t.length - 1 && Math.abs(t[ti + 1] - row.time_ps) < Math.abs(t[ti] - row.time_ps)) {
            ti++
          }
          row[key] = ti < msd.length ? msd[ti] : null
        })
      }
    })

    return { data: merged, keys: seriesKeys }
  }, [experiments])

  // For log scale, filter out zero/negative values
  const chartData = useMemo(() => {
    if (!logScale) return data
    return data
      .filter((d) => d.time_ps > 0)
      .map((d) => {
        const row = { time_ps: d.time_ps }
        keys.forEach(({ key }) => {
          row[key] = d[key] > 0 ? d[key] : null
        })
        return row
      })
  }, [data, keys, logScale])

  const handleExportCSV = () => {
    if (!chartData.length) return
    const filename = `msd_curve_${experiments.map((e) => e.expId || e.label).join('_')}`
    exportMultiSeriesToCSV(chartData, 'time_ps', keys, filename, { x: 'Time (ps)', y: 'MSD (Angstrom^2)' })
  }

  if (!data.length) {
    return <div className="text-xs text-slate-500 p-4 text-center">No MSD data available</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex justify-end gap-2 mb-2 flex-shrink-0">
        <button
          onClick={() => setLogScale((prev) => !prev)}
          className={`px-2 py-1 text-xs rounded border transition-colors ${
            logScale
              ? 'bg-blue-500/20 border-blue-400/40 text-blue-300'
              : 'bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300'
          }`}
        >
          Log-Log
        </button>
        <button
          onClick={handleExportCSV}
          className="px-2 py-1 text-xs rounded border bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300 flex items-center gap-1"
          title="Export to CSV"
        >
          <Download className="w-3 h-3" />
          CSV
        </button>
      </div>
      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="time_ps"
              type="number"
              scale={logScale ? 'log' : 'auto'}
              domain={logScale ? ['auto', 'auto'] : undefined}
              tickFormatter={(v) => (logScale ? v.toExponential(0) : v.toFixed(0))}
              label={{ value: 'Time (ps)', position: 'insideBottomRight', offset: -4, fontSize: 11, fill: '#94a3b8' }}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              stroke="#475569"
            />
            <YAxis
              scale={logScale ? 'log' : 'auto'}
              domain={logScale ? ['auto', 'auto'] : undefined}
              tickFormatter={(v) => (logScale ? v.toExponential(0) : v.toFixed(1))}
              label={{ value: 'MSD (\u00C5\u00B2)', angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#94a3b8' }}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              stroke="#475569"
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
              labelFormatter={(v) => `t = ${Number(v).toFixed(1)} ps`}
              formatter={(v, name) => {
                const entry = keys.find((k) => k.key === name)
                return [`${Number(v).toFixed(3)} \u00C5\u00B2`, entry?.label || name]
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

            {keys.map(({ key, index }) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={getChartColorByIndex(index)}
                strokeWidth={1.5}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Diffusion coefficient legend */}
      {keys.some((k) => k.metadata?.diffusion_coefficient_cm2s) && (
        <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-400 px-2">
          {keys
            .filter((k) => k.metadata?.diffusion_coefficient_cm2s)
            .map((k) => (
              <span key={k.key} style={{ color: getChartColorByIndex(k.index) }}>
                {k.label}: D = {Number(k.metadata.diffusion_coefficient_cm2s).toExponential(2)} cm\u00B2/s
              </span>
            ))}
        </div>
      )}
    </div>
  )
}
