import { useMemo, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts'
import { RefreshCw } from 'lucide-react'
import { useExperimentThermo } from '../hooks/useApi'
import { THERMO_COLORS } from '../lib/constants'
import useThemeVersion from '../hooks/useThemeVersion'

function ThermoChart({ expId }) {
  useThemeVersion('chart')
  const [activeLines, setActiveLines] = useState({
    temperature: true,
    pressure: true,
    density: true,
    volume: true,
  })

  const { data: thermoData, loading, error } = useExperimentThermo(expId)

  const data = useMemo(() => {
    if (!thermoData || !thermoData.Step) {
      return []
    }

    return thermoData.Step.map((step, i) => ({
      step,
      time: thermoData.Time?.[i] || step * 0.001,
      temperature: thermoData.Temp?.[i],
      pressure: thermoData.Press?.[i],
      density: thermoData.Density?.[i],
      volume: thermoData.Volume?.[i],
      energy: thermoData.PotEng?.[i] || thermoData.TotEng?.[i],
    }))
  }, [thermoData])

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-slate-400 text-sm">
        {error}
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-slate-400 text-sm">
        No thermo data available
      </div>
    )
  }

  const toggleLine = (key) => {
    setActiveLines((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div className="h-full flex flex-col">
      {/* Legend toggles */}
      <div className="flex items-center gap-4 mb-2 text-xs">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={activeLines.temperature}
            onChange={() => toggleLine('temperature')}
            className="w-3 h-3"
          />
          <span style={{ color: THERMO_COLORS.temperature }}>Temperature (K)</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={activeLines.pressure}
            onChange={() => toggleLine('pressure')}
            className="w-3 h-3"
          />
          <span style={{ color: THERMO_COLORS.pressure }}>Pressure (atm)</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={activeLines.density}
            onChange={() => toggleLine('density')}
            className="w-3 h-3"
          />
          <span style={{ color: THERMO_COLORS.density }}>Density (g/cm3)</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={activeLines.volume}
            onChange={() => toggleLine('volume')}
            className="w-3 h-3"
          />
          <span style={{ color: THERMO_COLORS.volume }}>Volume (Å³)</span>
        </label>
      </div>

      {/* Chart */}
      <div className="flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="time"
              stroke="#9CA3AF"
              fontSize={10}
              tickFormatter={(v) =>
                v >= 1000 ? `${(v / 1000).toFixed(1)} ns` : `${v.toFixed(0)} ps`
              }
            />
            <YAxis
              yAxisId="temp"
              orientation="left"
              stroke={THERMO_COLORS.temperature}
              fontSize={10}
              hide={!activeLines.temperature}
            />
            <YAxis
              yAxisId="pressure"
              orientation="right"
              stroke={THERMO_COLORS.pressure}
              fontSize={10}
              hide={!activeLines.pressure}
            />
            <YAxis
              yAxisId="density"
              orientation="right"
              stroke={THERMO_COLORS.density}
              fontSize={10}
              hide={!activeLines.density}
              domain={['auto', 'auto']}
            />
            <YAxis
              yAxisId="volume"
              orientation="right"
              stroke={THERMO_COLORS.volume}
              fontSize={10}
              hide={!activeLines.volume}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1E293B',
                border: '1px solid #475569',
                borderRadius: '8px',
                fontSize: '12px',
              }}
              labelFormatter={(v) => `Time: ${v.toFixed(1)} ps`}
            />
            {activeLines.temperature && (
              <Line
                yAxisId="temp"
                type="monotone"
                dataKey="temperature"
                stroke={THERMO_COLORS.temperature}
                dot={false}
                strokeWidth={1.5}
                name="Temp (K)"
              />
            )}
            {activeLines.pressure && (
              <Line
                yAxisId="pressure"
                type="monotone"
                dataKey="pressure"
                stroke={THERMO_COLORS.pressure}
                dot={false}
                strokeWidth={1.5}
                name="Press (atm)"
              />
            )}
            {activeLines.density && (
              <Line
                yAxisId="density"
                type="monotone"
                dataKey="density"
                stroke={THERMO_COLORS.density}
                dot={false}
                strokeWidth={1.5}
                name="Density (g/cm3)"
              />
            )}
            {activeLines.volume && (
              <Line
                yAxisId="volume"
                type="monotone"
                dataKey="volume"
                stroke={THERMO_COLORS.volume}
                dot={false}
                strokeWidth={1.5}
                name="Volume (Å³)"
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default ThermoChart
