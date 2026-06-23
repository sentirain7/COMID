import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { usePropertyByTemperature } from '../../hooks/useApi'
import { getAdditiveColor, getDataAgeClass, getDataAgeLabel } from '../../lib/chartUtils'
import { exportChartToCSV } from '../../lib/csvExport'
import useThemeVersion from '../../hooks/useThemeVersion'
import ScatterPlotBase from './ScatterPlotBase'

const METRIC_OPTIONS = [
  { value: 'density', label: 'Density (g/cm³)', unit: 'g/cm³' },
  { value: 'cohesive_energy_density', label: 'CED (MJ/m³)', unit: 'MJ/m³' },
  { value: 'viscosity', label: 'Viscosity (mPa·s)', unit: 'mPa·s' },
  { value: 'msd_diffusion_coefficient', label: 'Diffusion Coeff. (cm²/s)', unit: 'cm²/s' },
]

function TemperaturePropertyChart({ ffType = 'bulk_ff_gaff2' }) {
  useThemeVersion('chart')
  const [selectedMetric, setSelectedMetric] = useState('density')
  const [selectedAdditive, setSelectedAdditive] = useState('all')
  const { data, loading, error } = usePropertyByTemperature(selectedMetric, { ffType })

  const chartData = useMemo(() => {
    if (!data?.points?.length) {
      return { additives: [], points: [], hasRealData: false }
    }

    const points = data.points.map(p => ({
      x: p.temperature_k,
      y: p.value,
      temp: p.temperature_k,
      value: p.value,
      additive: p.additive || 'none',
      data_age: p.data_age,
      exp_id: p.exp_id,
      uncertainty: p.uncertainty,
    }))

    const additives = [...new Set(points.map(p => p.additive))]

    return {
      additives,
      points,
      hasRealData: true,
    }
  }, [data])

  const filteredPoints = useMemo(() => {
    if (selectedAdditive === 'all') return chartData.points
    return chartData.points.filter(p => p.additive === selectedAdditive)
  }, [chartData, selectedAdditive])

  const { tempRange, valueRange } = useMemo(() => {
    if (filteredPoints.length === 0) {
      return {
        tempRange: { min: 200, max: 400 },
        valueRange: { min: 0, max: 1 },
      }
    }
    const temps = filteredPoints.map(p => p.x)
    const values = filteredPoints.map(p => p.y)
    const minV = Math.min(...values)
    const maxV = Math.max(...values)
    const padV = (maxV - minV) * 0.1 || 0.01
    return {
      tempRange: {
        min: Math.min(...temps) - 20,
        max: Math.max(...temps) + 20,
      },
      valueRange: {
        min: minV - padV,
        max: maxV + padV,
      },
    }
  }, [filteredPoints])

  const normalizeX = (temp) => {
    return ((temp - tempRange.min) / (tempRange.max - tempRange.min)) * 100
  }

  const normalizeY = (value) => {
    return ((value - valueRange.min) / (valueRange.max - valueRange.min)) * 100
  }

  const metricInfo = METRIC_OPTIONS.find(m => m.value === selectedMetric) || METRIC_OPTIONS[0]

  const handleExportCSV = () => {
    if (!filteredPoints.length) return
    const exportData = filteredPoints.map(p => ({
      temperature_k: p.temp,
      [selectedMetric]: p.value,
      additive: p.additive,
      uncertainty: p.uncertainty || '',
      exp_id: p.exp_id || '',
    }))
    const filename = `property_vs_temperature_${selectedMetric}`
    exportChartToCSV(
      exportData,
      ['temperature_k', selectedMetric, 'additive', 'uncertainty', 'exp_id'],
      filename,
      {
        temperature_k: 'Temperature (K)',
        [selectedMetric]: metricInfo.label,
        additive: 'Additive',
        uncertainty: 'Uncertainty',
        exp_id: 'Experiment ID',
      }
    )
  }

  if (loading) {
    return (
      <div className="card p-4 h-full flex flex-col">
        <h3 className="text-lg font-semibold text-slate-200 mb-4">Property vs Temperature</h3>
        <div className="flex-1 flex items-center justify-center text-slate-400">
          Loading...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card p-4 h-full flex flex-col">
        <h3 className="text-lg font-semibold text-slate-200 mb-4">Property vs Temperature</h3>
        <div className="flex-1 flex items-center justify-center text-red-400">
          Error: {error.message}
        </div>
      </div>
    )
  }

  return (
    <div className="card p-4 h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-slate-200">Property vs Temperature</h3>
        <div className="flex items-center gap-2">
          <select
            value={selectedMetric}
            onChange={(e) => setSelectedMetric(e.target.value)}
            className="input w-48 text-sm"
          >
            {METRIC_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <button
            onClick={handleExportCSV}
            disabled={filteredPoints.length === 0}
            className="px-2 py-1 text-xs rounded border bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300 disabled:opacity-40 flex items-center gap-1"
            title="Export to CSV"
          >
            <Download className="w-3 h-3" />
            CSV
          </button>
        </div>
      </div>

      {chartData.points.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-slate-400">
          No data available for {selectedMetric}
        </div>
      ) : (
        <div className="flex-1">
        <ScatterPlotBase
          title=""
          showMockLabel={!chartData.hasRealData}
          loading={false}
          additives={chartData.additives.map(a => a === 'none' ? 'None' : a)}
          selectedAdditive={selectedAdditive === 'all' ? 'all' : (selectedAdditive === 'none' ? 'None' : selectedAdditive)}
          onAdditiveChange={(v) => setSelectedAdditive(v === 'all' ? 'all' : (v === 'None' ? 'none' : v))}
          points={filteredPoints.map(p => ({
            ...p,
            additive: p.additive === 'none' ? 'None' : p.additive,
          }))}
          xLabel="Temp. (K)"
          yLabel={metricInfo.unit}
          xTickLabels={[
            `${tempRange.min.toFixed(0)}K`,
            `${((tempRange.max + tempRange.min) / 2).toFixed(0)}K`,
            `${tempRange.max.toFixed(0)}K`,
          ]}
          yTickLabels={[
            valueRange.max.toFixed(4),
            ((valueRange.max + valueRange.min) / 2).toFixed(4),
            valueRange.min.toFixed(4),
          ]}
          normalizeX={normalizeX}
          normalizeY={normalizeY}
          gridLinesX
          renderTooltip={(point) => (
            <>
              <div className="text-white font-medium">{point.temp} K</div>
              <div className="text-slate-400">
                {metricInfo.label.split(' ')[0]}: {point.value?.toFixed(4)} {metricInfo.unit}
              </div>
              {point.uncertainty && (
                <div className="text-slate-400">
                  Uncertainty: ±{point.uncertainty.toFixed(4)}
                </div>
              )}
              <div style={{ color: getAdditiveColor(point.additive === 'None' ? 'none' : point.additive) }}>
                Additive: {point.additive}
              </div>
              {point.exp_id && (
                <div className="text-slate-500 text-xs mt-1">
                  {point.exp_id}
                </div>
              )}
              {point.data_age && (
                <div className={`mt-1 ${getDataAgeClass(point.data_age)}`}>
                  {getDataAgeLabel(point.data_age)}
                </div>
              )}
            </>
          )}
        />
        </div>
      )}

      <div className="mt-2 text-xs text-slate-500">
        FF Type: {ffType} | Points: {data?.points?.length || 0}
      </div>
    </div>
  )
}

export default TemperaturePropertyChart
