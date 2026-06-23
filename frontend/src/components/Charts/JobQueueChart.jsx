import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { Loader2 } from 'lucide-react'
import { TIER_COLORS } from '../../lib/constants'
import useThemeVersion from '../../hooks/useThemeVersion'

function JobQueueChart({ stats, loading }) {
  useThemeVersion('chart')
  // Convert jobs_by_tier to chart data
  const data = stats?.jobs_by_tier
    ? Object.entries(stats.jobs_by_tier).map(([tier, count]) => ({
        name: tier.charAt(0).toUpperCase() + tier.slice(1),
        value: count,
        tier,
      }))
    : [
        { name: 'Screening', value: 5, tier: 'screening' },
        { name: 'Confirm', value: 2, tier: 'confirm' },
        { name: 'Viscosity', value: 1, tier: 'viscosity' },
        { name: 'Validation', value: 0, tier: 'validation' },
      ]

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 shadow-lg">
          <p className="text-white font-medium">{payload[0].payload.name}</p>
          <p className="text-slate-300 text-sm">{payload[0].value} jobs</p>
        </div>
      )
    }
    return null
  }

  const hasRealData = stats?.jobs_by_tier && Object.keys(stats.jobs_by_tier).length > 0

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="text-lg font-semibold text-white">
          Jobs by Tier
          {!hasRealData && !loading && <span className="text-xs text-slate-500 ml-2">(Mock Data)</span>}
        </h2>
      </div>
      <div className="card-body">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
          </div>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="name"
                  tick={{ fill: '#94a3b8', fontSize: 12 }}
                  axisLine={{ stroke: '#334155' }}
                />
                <YAxis
                  tick={{ fill: '#94a3b8', fontSize: 12 }}
                  axisLine={{ stroke: '#334155' }}
                  allowDecimals={false}
                />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {data.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={TIER_COLORS[entry.tier] || '#6b7280'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}

export default JobQueueChart
