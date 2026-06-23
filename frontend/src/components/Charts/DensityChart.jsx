import { useMemo, useState } from 'react'
import { useDensityTemperature } from '../../hooks/useApi'
import { getAdditiveColor, getDataAgeClass, getDataAgeLabel } from '../../lib/chartUtils'
import useThemeVersion from '../../hooks/useThemeVersion'
import ScatterPlotBase from './ScatterPlotBase'

/**
 * Density vs Temperature Chart Component
 * Shows density trends by temperature with additive coloring
 */
function DensityChart() {
  useThemeVersion('chart')
  const [selectedAdditive, setSelectedAdditive] = useState('all')
  const { data: apiData, loading } = useDensityTemperature('bulk_ff_gaff2', 30000)

  const chartData = useMemo(() => {
    // Check if we have real API data
    if (apiData?.points && apiData.points.length > 0) {
      const points = apiData.points.map(p => ({
        x: p.temperature_k,
        y: p.density,
        temp: p.temperature_k,
        density: p.density,
        additive: p.additive || 'None',
        data_age: p.data_age,
        exp_id: p.exp_id,
        run_tier: p.run_tier,
      }))

      // Get unique additives
      const additives = [...new Set(points.map(p => p.additive))]

      return {
        additives: additives,
        points: points,
        hasRealData: true,
      }
    }

    // Mock data for development
    return {
      additives: ['None', 'PPA', 'SBS', 'Sulfur', 'WMA'],
      points: [
        { x: 233, y: 1.08, temp: 233, density: 1.08, additive: 'None', data_age: 'historical' },
        { x: 253, y: 1.06, temp: 253, density: 1.06, additive: 'PPA', data_age: 'historical' },
        { x: 273, y: 1.04, temp: 273, density: 1.04, additive: 'SBS', data_age: 'historical' },
        { x: 293, y: 1.02, temp: 293, density: 1.02, additive: 'None', data_age: 'today' },
        { x: 298, y: 1.015, temp: 298, density: 1.015, additive: 'PPA', data_age: 'current_session' },
        { x: 313, y: 1.00, temp: 313, density: 1.00, additive: 'SBS', data_age: 'current_session' },
        { x: 333, y: 0.98, temp: 333, density: 0.98, additive: 'Sulfur', data_age: 'today' },
        { x: 353, y: 0.96, temp: 353, density: 0.96, additive: 'WMA', data_age: 'historical' },
        { x: 373, y: 0.94, temp: 373, density: 0.94, additive: 'None', data_age: 'historical' },
        { x: 393, y: 0.92, temp: 393, density: 0.92, additive: 'PPA', data_age: 'historical' },
      ],
      hasRealData: false,
    }
  }, [apiData])

  const filteredPoints = useMemo(() => {
    if (selectedAdditive === 'all') return chartData.points
    return chartData.points.filter(p => p.additive === selectedAdditive)
  }, [chartData, selectedAdditive])

  // Calculate ranges
  const { tempRange, densityRange } = useMemo(() => {
    const temps = filteredPoints.map(p => p.x)
    const densities = filteredPoints.map(p => p.y)
    return {
      tempRange: {
        min: Math.min(...temps) - 20,
        max: Math.max(...temps) + 20,
      },
      densityRange: {
        min: Math.min(...densities) - 0.05,
        max: Math.max(...densities) + 0.05,
      },
    }
  }, [filteredPoints])

  const normalizeX = (temp) => {
    return ((temp - tempRange.min) / (tempRange.max - tempRange.min)) * 100
  }

  const normalizeY = (density) => {
    return ((density - densityRange.min) / (densityRange.max - densityRange.min)) * 100
  }

  return (
    <ScatterPlotBase
      title="Density vs Temperature"
      showMockLabel={!chartData.hasRealData}
      loading={loading}
      additives={chartData.additives}
      selectedAdditive={selectedAdditive}
      onAdditiveChange={setSelectedAdditive}
      points={filteredPoints}
      xLabel="Temp. (K)"
      yLabel="ρ (g/cm³)"
      xTickLabels={[
        `${tempRange.min.toFixed(0)}K`,
        `${((tempRange.max + tempRange.min) / 2).toFixed(0)}K`,
        `${tempRange.max.toFixed(0)}K`,
      ]}
      yTickLabels={[
        densityRange.max.toFixed(2),
        ((densityRange.max + densityRange.min) / 2).toFixed(2),
        densityRange.min.toFixed(2),
      ]}
      normalizeX={normalizeX}
      normalizeY={normalizeY}
      gridLinesX
      referenceLines={
        densityRange.min < 1.0 && densityRange.max > 1.0
          ? [{ value: 1.0, label: '1.0' }]
          : []
      }
      renderTooltip={(point) => (
        <>
          <div className="text-white font-medium">{point.temp} K</div>
          <div className="text-slate-400">Density: {point.density?.toFixed(3)} g/cm³</div>
          <div style={{ color: getAdditiveColor(point.additive) }}>
            Additive: {point.additive}
          </div>
          {point.run_tier && (
            <div className="text-slate-400">Tier: {point.run_tier}</div>
          )}
          {point.data_age && (
            <div className={`mt-1 ${getDataAgeClass(point.data_age)}`}>
              {getDataAgeLabel(point.data_age)}
            </div>
          )}
        </>
      )}
    />
  )
}

export default DensityChart
