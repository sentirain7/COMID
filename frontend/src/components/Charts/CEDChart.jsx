import { useMemo, useState } from 'react'
import { getDataAgeClass, getDataAgeLabel } from '../../lib/chartUtils'
import ScatterPlotBase from './ScatterPlotBase'

/**
 * CED vs Additive Chart Component
 * Shows Cohesive Energy Density trends by additive type and concentration
 */
function CEDChart({ data, loading }) {
  const [selectedAdditive, setSelectedAdditive] = useState('all')

  const chartData = useMemo(() => {
    // Check if we have real API data (from /metrics/ced-by-additive)
    if (data?.points && data.points.length > 0) {
      // Transform API data to chart format
      const points = data.points.map(p => ({
        x: p.additive_wt || 0,
        y: p.ced,
        additive: p.additive || 'None',
        concentration: p.additive_wt || 0,
        ced: p.ced,
        temp: p.temperature_k || 298,
        data_age: p.data_age,
        exp_id: p.exp_id,
      }))
      return {
        additives: data.additives || ['None', 'PPA', 'SBS', 'Sulfur', 'WMA'],
        points: points,
        hasRealData: true,
      }
    }

    // Mock data for development with data_age
    return {
      additives: ['None', 'PPA', 'SBS', 'Sulfur', 'WMA'],
      points: [
        { x: 0, y: 285, additive: 'None', concentration: 0, ced: 285, temp: 298, data_age: 'historical' },
        { x: 1, y: 290, additive: 'PPA', concentration: 1, ced: 290, temp: 298, data_age: 'historical' },
        { x: 2, y: 295, additive: 'PPA', concentration: 2, ced: 295, temp: 298, data_age: 'today' },
        { x: 3, y: 302, additive: 'PPA', concentration: 3, ced: 302, temp: 298, data_age: 'current_session' },
        { x: 2, y: 288, additive: 'SBS', concentration: 2, ced: 288, temp: 298, data_age: 'historical' },
        { x: 4, y: 292, additive: 'SBS', concentration: 4, ced: 292, temp: 298, data_age: 'today' },
        { x: 6, y: 298, additive: 'SBS', concentration: 6, ced: 298, temp: 298, data_age: 'current_session' },
        { x: 0.5, y: 287, additive: 'Sulfur', concentration: 0.5, ced: 287, temp: 298, data_age: 'historical' },
        { x: 1, y: 291, additive: 'Sulfur', concentration: 1, ced: 291, temp: 298, data_age: 'historical' },
        { x: 1, y: 283, additive: 'WMA', concentration: 1, ced: 283, temp: 298, data_age: 'today' },
        { x: 2, y: 280, additive: 'WMA', concentration: 2, ced: 280, temp: 298, data_age: 'current_session' },
      ],
      hasRealData: false,
    }
  }, [data])

  const filteredPoints = useMemo(() => {
    if (selectedAdditive === 'all') return chartData.points
    return chartData.points.filter(p => p.additive === selectedAdditive)
  }, [chartData, selectedAdditive])

  const cedRange = useMemo(() => {
    const ceds = filteredPoints.map(p => p.y)
    return {
      min: Math.min(...ceds) - 10,
      max: Math.max(...ceds) + 10
    }
  }, [filteredPoints])

  const normalizeY = (ced) => {
    return ((ced - cedRange.min) / (cedRange.max - cedRange.min)) * 100
  }

  return (
    <ScatterPlotBase
      title="CED vs Additive Concentration"
      showMockLabel={!chartData.hasRealData}
      loading={loading}
      additives={chartData.additives}
      selectedAdditive={selectedAdditive}
      onAdditiveChange={setSelectedAdditive}
      points={filteredPoints}
      xLabel="Additive Conc. (wt%)"
      yLabel="CED (MJ/m³)"
      xTickLabels={['0%', '5%', '10%']}
      yTickLabels={[
        cedRange.max.toFixed(0),
        ((cedRange.max + cedRange.min) / 2).toFixed(0),
        cedRange.min.toFixed(0),
      ]}
      normalizeX={(value) => (value / 10) * 100}
      normalizeY={normalizeY}
      renderTooltip={(point) => (
        <>
          <div className="text-white font-medium">{point.additive}</div>
          <div className="text-slate-400">Conc: {point.concentration}%</div>
          <div className="text-slate-400">CED: {point.ced?.toFixed(1)} MJ/m³</div>
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

export default CEDChart
