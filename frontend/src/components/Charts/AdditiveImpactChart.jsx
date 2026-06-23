import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { usePropertyByAdditive } from '../../hooks/useApi'
import { getAdditiveColor } from '../../lib/chartUtils'
import { exportChartToCSV } from '../../lib/csvExport'
import useThemeVersion from '../../hooks/useThemeVersion'

const METRIC_OPTIONS = [
  { value: 'density', label: 'Density (g/cm³)', unit: 'g/cm³' },
  { value: 'cohesive_energy_density', label: 'CED (MJ/m³)', unit: 'MJ/m³' },
  { value: 'viscosity', label: 'Viscosity (mPa·s)', unit: 'mPa·s' },
  { value: 'msd_diffusion_coefficient', label: 'Diffusion Coeff. (cm²/s)', unit: 'cm²/s' },
]

const TEMPERATURE_OPTIONS = [
  { value: null, label: 'All Temperatures' },
  { value: 273, label: '273 K' },
  { value: 293, label: '293 K' },
  { value: 313, label: '313 K' },
  { value: 333, label: '333 K' },
  { value: 373, label: '373 K' },
]

function AdditiveImpactChart({ ffType = 'bulk_ff_gaff2' }) {
  useThemeVersion('chart')
  const [selectedMetric, setSelectedMetric] = useState('density')
  const [selectedTemp, setSelectedTemp] = useState(null)
  const { data, loading, error } = usePropertyByAdditive(selectedMetric, {
    ffType,
    temperatureK: selectedTemp,
  })

  const chartData = useMemo(() => {
    if (!data?.additives?.length || !data?.points?.length) {
      return { bars: [], maxValue: 0 }
    }

    // Calculate mean and std for each additive
    const stats = {}
    data.additives.forEach(additive => {
      const points = data.points.filter(p => p.additive === additive)
      if (points.length === 0) return

      const values = points.map(p => p.value)
      const mean = values.reduce((a, b) => a + b, 0) / values.length
      const variance = values.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / values.length
      const std = Math.sqrt(variance)

      stats[additive] = { mean, std, count: points.length }
    })

    const bars = data.additives
      .filter(a => stats[a])
      .map(additive => ({
        label: additive === 'none' ? 'No Additive' : additive,
        additive,
        mean: stats[additive].mean,
        std: stats[additive].std,
        count: stats[additive].count,
        color: getAdditiveColor(additive),
      }))

    const maxValue = Math.max(...bars.map(b => b.mean + b.std), 1e-9)

    return { bars, maxValue }
  }, [data])

  const metricInfo = METRIC_OPTIONS.find(m => m.value === selectedMetric) || METRIC_OPTIONS[0]

  const handleExportCSV = () => {
    if (!chartData.bars.length) return
    const exportData = chartData.bars.map(b => ({
      additive: b.label,
      mean: b.mean,
      std: b.std,
      sample_count: b.count,
    }))
    const filename = `property_by_additive_${selectedMetric}${selectedTemp ? `_${selectedTemp}K` : ''}`
    exportChartToCSV(
      exportData,
      ['additive', 'mean', 'std', 'sample_count'],
      filename,
      {
        additive: 'Additive',
        mean: `Mean ${metricInfo.label}`,
        std: 'Standard Deviation',
        sample_count: 'Sample Count',
      }
    )
  }

  return (
    <div className="card p-4 h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-slate-200">Property by Additive</h3>
          <p className="text-xs text-slate-500">Mean values per additive type (not baseline-adjusted)</p>
        </div>
        <div className="flex gap-2 items-center">
          <select
            value={selectedMetric}
            onChange={(e) => setSelectedMetric(e.target.value)}
            className="input w-40 text-sm"
          >
            {METRIC_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <select
            value={selectedTemp || ''}
            onChange={(e) => setSelectedTemp(e.target.value ? Number(e.target.value) : null)}
            className="input w-36 text-sm"
          >
            {TEMPERATURE_OPTIONS.map((opt) => (
              <option key={opt.value || 'all'} value={opt.value || ''}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            onClick={handleExportCSV}
            disabled={chartData.bars.length === 0}
            className="px-2 py-1 text-xs rounded border bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300 disabled:opacity-40 flex items-center gap-1"
            title="Export to CSV"
          >
            <Download className="w-3 h-3" />
            CSV
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex-1 flex items-center justify-center text-slate-400">
          Loading...
        </div>
      )}

      {error && (
        <div className="flex-1 flex items-center justify-center text-red-400">
          Error: {error.message}
        </div>
      )}

      {!loading && !error && chartData.bars.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-slate-400">
          No data available for {selectedMetric}
        </div>
      )}

      {!loading && !error && chartData.bars.length > 0 && (
        <div className="flex-1 space-y-2 overflow-y-auto">
          {chartData.bars.map((bar) => {
            const pct = (bar.mean / chartData.maxValue) * 100
            const errorPct = (bar.std / chartData.maxValue) * 100
            return (
              <div key={bar.additive} className="group relative">
                <div className="flex items-center gap-3">
                  <span className="w-24 text-xs text-slate-300 truncate text-right" title={bar.label}>
                    {bar.label}
                  </span>
                  <div className="flex-1 h-6 bg-slate-800 rounded overflow-visible relative">
                    {/* Main bar */}
                    <div
                      className="h-full rounded transition-all"
                      style={{
                        width: `${Math.min(pct, 100)}%`,
                        backgroundColor: bar.color,
                        opacity: 0.8,
                      }}
                    />
                    {/* Error indicator */}
                    {bar.std > 0 && (
                      <div
                        className="absolute top-1/2 -translate-y-1/2 h-3 border-l border-r border-slate-400"
                        style={{
                          left: `${Math.max(0, pct - errorPct)}%`,
                          width: `${Math.min(errorPct * 2, 100 - Math.max(0, pct - errorPct))}%`,
                        }}
                      />
                    )}
                  </div>
                  <span className="w-20 text-xs text-slate-400 tabular-nums">
                    {bar.mean.toFixed(4)}
                  </span>
                </div>
                {/* Tooltip */}
                <div className="absolute left-28 top-full mt-1 z-10 hidden group-hover:block bg-slate-700 rounded px-2 py-1 text-xs shadow-lg">
                  <div className="text-white">Mean: {bar.mean.toFixed(4)} {metricInfo.unit}</div>
                  <div className="text-slate-300">Std: ±{bar.std.toFixed(4)}</div>
                  <div className="text-slate-400">Samples: {bar.count}</div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="mt-4 text-xs text-slate-500">
        FF Type: {ffType} | Additives: {data?.additives?.length || 0} | Points: {data?.points?.length || 0}
      </div>
    </div>
  )
}

export default AdditiveImpactChart
