import { Link } from 'react-router-dom'
import { ExternalLink, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { FFFilterBadge } from './FFFilter'
import { StatusBadge, TierBadge } from './shared'

function RecentResults({ experiments, loading, ffType = 'bulk_ff_gaff2' }) {
  // Mock data for demonstration
  const mockExperiments = [
    {
      exp_id: 'exp_001',
      status: 'completed',
      run_tier: 'screening',
      ff_type: 'bulk_ff_gaff2',
      temperature_k: 298,
      metrics: { density: 1.023, ced: 234.5 },
      created_at: '2026-01-26T10:00:00Z',
      data_age: 'historical',
    },
    {
      exp_id: 'exp_002',
      status: 'running',
      run_tier: 'screening',
      ff_type: 'bulk_ff_gaff2',
      temperature_k: 313,
      metrics: null,
      created_at: '2026-01-27T11:00:00Z',
      data_age: 'current_session',
    },
    {
      exp_id: 'exp_003',
      status: 'queued',
      run_tier: 'confirm',
      ff_type: 'bulk_ff_gaff2',
      temperature_k: 298,
      metrics: null,
      created_at: '2026-01-27T11:30:00Z',
      data_age: 'current_session',
    },
  ]

  const displayExperiments = experiments.length > 0 ? experiments : mockExperiments

  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Recent Results</h2>
        <Link
          to="/experiments"
          className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
        >
          View All
          <ExternalLink className="w-4 h-4" />
        </Link>
      </div>
      <div className="overflow-x-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Experiment ID</th>
                <th>Status</th>
                <th>Tier</th>
                <th>FF</th>
                <th>Temp (K)</th>
                <th>Density (g/cm3)</th>
                <th>CED (MJ/m3)</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {displayExperiments.map((exp) => (
                <tr
                  key={exp.exp_id}
                  className={clsx(
                    exp.data_age === 'historical' && 'opacity-50',
                    exp.data_age === 'current_session' && 'bg-blue-500/5 border-l-2 border-l-blue-500'
                  )}
                >
                  <td>
                    <Link
                      to={`/experiments/${exp.exp_id}`}
                      className="text-blue-400 hover:text-blue-300 font-mono text-sm"
                    >
                      {exp.exp_id}
                    </Link>
                  </td>
                  <td>
                    <StatusBadge status={exp.status} />
                  </td>
                  <td>
                    <TierBadge tier={exp.run_tier} />
                  </td>
                  <td>
                    <FFFilterBadge ffType={exp.ff_type || ffType} />
                  </td>
                  <td>{exp.temperature_k || '-'}</td>
                  <td>
                    {exp.metrics?.density
                      ? exp.metrics.density.toFixed(3)
                      : '-'}
                  </td>
                  <td>
                    {exp.metrics?.ced
                      ? exp.metrics.ced.toFixed(1)
                      : '-'}
                  </td>
                  <td className="text-slate-400 text-sm">
                    {exp.created_at
                      ? new Date(exp.created_at).toLocaleString()
                      : '-'}
                  </td>
                </tr>
              ))}
              {displayExperiments.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center py-8 text-slate-400">
                    No experiments found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default RecentResults
