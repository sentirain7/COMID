import { useMemo } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceDot,
} from 'recharts'

export default function StressStrainChart({ strain, stressMPa, peakIndex }) {
  const data = useMemo(() => {
    if (!strain?.length || !stressMPa?.length) return []
    return strain.map((s, i) => ({ strain: s, stress: stressMPa[i] }))
  }, [strain, stressMPa])

  if (!data.length) {
    return <div className="text-xs text-slate-500 p-4 text-center">No stress-strain data</div>
  }

  const peak = peakIndex != null && data[peakIndex] ? data[peakIndex] : null

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="strain"
          type="number"
          tickFormatter={(v) => v.toFixed(2)}
          label={{ value: 'Strain', position: 'insideBottomRight', offset: -4, fontSize: 11, fill: '#94a3b8' }}
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
        />
        <YAxis
          label={{ value: 'Stress (MPa)', angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#94a3b8' }}
          tick={{ fontSize: 10, fill: '#94a3b8' }}
          stroke="#475569"
        />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
          labelFormatter={(v) => `Strain: ${Number(v).toFixed(4)}`}
          formatter={(v) => [`${Number(v).toFixed(2)} MPa`, 'Stress']}
        />
        <Line type="monotone" dataKey="stress" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
        {peak && (
          <ReferenceDot
            x={peak.strain}
            y={peak.stress}
            r={4}
            fill="#ef4444"
            stroke="#ef4444"
            label={{ value: `${peak.stress.toFixed(1)} MPa`, position: 'top', fontSize: 10, fill: '#ef4444' }}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}
