import { useMemo } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceDot,
  Legend,
} from 'recharts'
import { Download } from 'lucide-react'
import { getChartColorByIndex } from '../../lib/chartUtils'
import { exportMultiSeriesToCSV } from '../../lib/csvExport'

/**
 * RDF curve chart — multi-experiment overlay.
 *
 * Props:
 *   experiments: [{ expId, label, columns: { r, g_r }, metadata }]
 */
export default function RdfCurveChart({ experiments = [] }) {
  const { data, keys } = useMemo(() => {
    if (!experiments.length) return { data: [], keys: [] }

    // Build merged dataset keyed by r values from first experiment
    const baseR = experiments[0]?.columns?.r || []
    if (!baseR.length) return { data: [], keys: [] }

    const merged = baseR.map((r) => ({ r }))
    const seriesKeys = []

    experiments.forEach((exp, i) => {
      const r = exp.columns?.r || []
      const gr = exp.columns?.g_r || []
      const key = `g_r_${i}`
      seriesKeys.push({ key, label: exp.label || exp.expId, index: i })

      // Match by index (same x-grid) or by closest r value
      if (r.length === baseR.length) {
        gr.forEach((val, j) => {
          merged[j][key] = val
        })
      } else {
        // Different grid — interpolate by nearest r
        let ri = 0
        merged.forEach((row) => {
          while (ri < r.length - 1 && Math.abs(r[ri + 1] - row.r) < Math.abs(r[ri] - row.r)) {
            ri++
          }
          row[key] = ri < gr.length ? gr[ri] : null
        })
      }
    })

    return { data: merged, keys: seriesKeys }
  }, [experiments])

  const handleExportCSV = () => {
    if (!data.length) return
    const filename = `rdf_curve_${experiments.map((e) => e.expId || e.label).join('_')}`
    exportMultiSeriesToCSV(data, 'r', keys, filename, { x: 'r (Angstrom)', y: 'g(r)' })
  }

  if (!data.length) {
    return <div className="text-xs text-slate-500 p-4 text-center">No RDF data available</div>
  }

  // Collect first peak markers from metadata
  const peaks = experiments
    .map((exp, i) => {
      const meta = exp.metadata || {}
      if (meta.first_peak_r != null && meta.first_peak_g != null) {
        return { r: meta.first_peak_r, g: meta.first_peak_g, index: i }
      }
      return null
    })
    .filter(Boolean)

  return (
    <div className="h-full flex flex-col">
      <div className="flex justify-end mb-2 flex-shrink-0">
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
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="r"
              type="number"
              tickFormatter={(v) => v.toFixed(1)}
              label={{ value: 'r (\u00C5)', position: 'insideBottomRight', offset: -4, fontSize: 11, fill: '#94a3b8' }}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              stroke="#475569"
            />
            <YAxis
              label={{ value: 'g(r)', angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#94a3b8' }}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              stroke="#475569"
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
              labelFormatter={(v) => `r = ${Number(v).toFixed(3)} \u00C5`}
              formatter={(v, name) => {
                const entry = keys.find((k) => k.key === name)
                return [`${Number(v).toFixed(4)}`, entry?.label || name]
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

            {/* Ideal gas reference line at g(r) = 1 */}
            <ReferenceLine y={1} stroke="#64748b" strokeDasharray="4 4" label={{ value: 'g(r)=1', fontSize: 10, fill: '#64748b', position: 'right' }} />

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

            {peaks.map((p) => (
              <ReferenceDot
                key={`peak-${p.index}`}
                x={p.r}
                y={p.g}
                r={4}
                fill={getChartColorByIndex(p.index)}
                stroke={getChartColorByIndex(p.index)}
                label={{ value: `${p.g.toFixed(2)}`, position: 'top', fontSize: 9, fill: getChartColorByIndex(p.index) }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
