import { useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Legend,
} from 'recharts'
import { Download } from 'lucide-react'
import { getChartColorByIndex } from '../../lib/chartUtils'
import { exportMultiSeriesToCSV } from '../../lib/csvExport'

/**
 * RDF pair curve chart — shows RDF between specific molecular group pairs.
 *
 * Props:
 *   experiments: [{ expId, label, columns: { r, g_r, pair_label }, metadata }]
 */
export default function RdfPairCurveChart({ experiments = [] }) {
  const [selectedPairs, setSelectedPairs] = useState([])

  // Extract unique pair labels from all experiments
  const availablePairs = useMemo(() => {
    const pairSet = new Set()
    experiments.forEach((exp) => {
      const labels = exp.columns?.pair_label || []
      labels.forEach((p) => pairSet.add(p))
    })
    return [...pairSet].sort()
  }, [experiments])

  // Initialize selection when pairs change
  useMemo(() => {
    if (availablePairs.length && selectedPairs.length === 0) {
      // Select first pair by default
      setSelectedPairs([availablePairs[0]])
    }
  }, [availablePairs, selectedPairs.length])

  // Build chart data for selected pairs
  const { data, keys } = useMemo(() => {
    if (!experiments.length || !selectedPairs.length) return { data: [], keys: [] }

    // Use first experiment's r values as base
    const exp = experiments[0]
    const allR = exp.columns?.r || []
    const allGr = exp.columns?.g_r || []
    const allPairLabels = exp.columns?.pair_label || []

    if (!allR.length) return { data: [], keys: [] }

    // Group data by pair_label
    const pairData = {}
    allR.forEach((r, i) => {
      const pairLabel = allPairLabels[i]
      if (!pairLabel || !selectedPairs.includes(pairLabel)) return
      if (!pairData[pairLabel]) pairData[pairLabel] = []
      pairData[pairLabel].push({ r, g_r: allGr[i] })
    })

    // Find common r grid
    const firstPair = selectedPairs.find((p) => pairData[p]?.length)
    if (!firstPair) return { data: [], keys: [] }

    const baseData = pairData[firstPair]
    const merged = baseData.map((d) => ({ r: d.r }))
    const seriesKeys = []

    selectedPairs.forEach((pairLabel, i) => {
      if (!pairData[pairLabel]) return
      const key = `g_r_${i}`
      seriesKeys.push({ key, label: formatPairLabel(pairLabel), pairLabel, index: i })

      pairData[pairLabel].forEach((d, j) => {
        if (merged[j]) {
          merged[j][key] = d.g_r
        }
      })
    })

    return { data: merged, keys: seriesKeys }
  }, [experiments, selectedPairs])

  const togglePair = (pairLabel) => {
    setSelectedPairs((prev) => {
      if (prev.includes(pairLabel)) {
        return prev.filter((p) => p !== pairLabel)
      }
      return [...prev, pairLabel]
    })
  }

  const handleExportCSV = () => {
    if (!data.length) return
    const filename = `rdf_pair_curve_${experiments[0]?.expId || 'data'}`
    exportMultiSeriesToCSV(data, 'r', keys, filename, { x: 'r (Angstrom)', y: 'g(r)' })
  }

  if (!experiments.length) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-slate-500">
        No RDF pair data available
      </div>
    )
  }

  if (!availablePairs.length) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-slate-500">
        No pair-type RDF data found. Run simulations with SARA group assignments to generate pair RDF.
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Pair selector */}
      <div className="flex items-center gap-2 mb-2 flex-shrink-0 flex-wrap">
        <span className="text-xs text-slate-400">Pairs:</span>
        {availablePairs.map((pair) => (
          <button
            key={pair}
            onClick={() => togglePair(pair)}
            className={`px-2 py-0.5 text-xs rounded border transition-colors ${
              selectedPairs.includes(pair)
                ? 'bg-blue-500/20 border-blue-400/40 text-blue-300'
                : 'bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300'
            }`}
          >
            {formatPairLabel(pair)}
          </button>
        ))}
        <button
          onClick={handleExportCSV}
          disabled={!data.length}
          className="ml-auto px-2 py-0.5 text-xs rounded border bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300 disabled:opacity-40 flex items-center gap-1"
          title="Export to CSV"
        >
          <Download className="w-3 h-3" />
          CSV
        </button>
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0">
        {data.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="r"
                type="number"
                tickFormatter={(v) => v.toFixed(1)}
                label={{
                  value: 'r (\u00C5)',
                  position: 'insideBottomRight',
                  offset: -4,
                  fontSize: 11,
                  fill: '#94a3b8',
                }}
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                stroke="#475569"
              />
              <YAxis
                label={{
                  value: 'g(r)',
                  angle: -90,
                  position: 'insideLeft',
                  offset: 10,
                  fontSize: 11,
                  fill: '#94a3b8',
                }}
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                stroke="#475569"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: 6,
                  fontSize: 11,
                }}
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
              <ReferenceLine
                y={1}
                stroke="#64748b"
                strokeDasharray="4 4"
                label={{ value: 'g(r)=1', fontSize: 10, fill: '#64748b', position: 'right' }}
              />

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
        ) : (
          <div className="h-full flex items-center justify-center text-xs text-slate-500">
            Select at least one pair to display RDF
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Format pair label for display
 * e.g., "asphaltene_saturate" -> "Asphaltene - Saturate"
 */
function formatPairLabel(pairLabel) {
  if (!pairLabel) return ''
  return pairLabel
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' - ')
}
