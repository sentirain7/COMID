import { RefreshCw, FileText, AlertTriangle } from 'lucide-react'
import { useExperimentDetail, useExperimentMetrics } from '../../hooks/useApi'
import { EIntraMethodBadge, MetricsTable, StatusBadge } from '../shared/index'
import ThermoChart from '../ThermoChart'
import MoleculeViewer from '../MoleculeViewer'

function DynamicsExperimentDetail({ expId }) {
  const { data: experiment, loading: expLoading, error: expError } =
    useExperimentDetail(expId)
  const { data: metrics } = useExperimentMetrics(expId)

  if (!expId) {
    return (
      <div className="h-full flex items-center justify-center text-slate-400">
        <div className="text-center">
          <FileText className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Select an experiment to view details</p>
        </div>
      </div>
    )
  }

  if (expLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
      </div>
    )
  }

  if (expError) {
    return (
      <div className="h-full flex items-center justify-center text-red-400">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 mx-auto mb-3" />
          <p className="text-sm">Error: {expError}</p>
        </div>
      </div>
    )
  }

  const exp = experiment
  const eIntraProvenance = exp?.e_intra_method_resolved_from || exp?.e_intra_method_origin || exp?.e_intra_method_source || null
  const summaryCards = [
    { label: 'Molecule', value: exp.additive_mol_id || exp.additive_label || '-' },
    { label: 'Temp', value: exp.temperature_k != null ? `${exp.temperature_k} K` : '-' },
    { label: 'Atoms', value: exp.actual_atoms ? Number(exp.actual_atoms).toLocaleString() : (exp.target_atoms ? Number(exp.target_atoms).toLocaleString() : '-') },
    { label: 'Status', value: null, badge: exp.status },
    { label: 'FF', value: exp.force_field_type || exp.ff_type || '-' },
    { label: 'Wall Time', value: exp.wall_time_seconds != null ? `${(exp.wall_time_seconds / 60).toFixed(1)} min` : '-' },
  ]

  return (
    <div className="h-full overflow-y-auto space-y-3">
      <div className="bg-slate-700/30 rounded-lg px-3 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-white font-mono break-all">{exp.exp_id}</h3>
          <EIntraMethodBadge
            method={exp.e_intra_method}
            source={eIntraProvenance}
            scope="e_intra"
          />
        </div>
      </div>

      <div className="bg-slate-700/30 rounded-lg px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          {summaryCards.map((card) => (
            <span key={card.label} className="text-slate-400">
              {card.label}{' '}
              {card.badge
                ? <StatusBadge status={card.badge} size="sm" />
                : <span className="text-slate-100">{card.value}</span>
              }
            </span>
          ))}
        </div>
      </div>

      <div className="bg-slate-700/30 rounded-lg p-3">
        <h4 className="text-xs font-semibold text-slate-400 mb-2">Thermodynamics</h4>
        <div className="h-72">
          <ThermoChart expId={expId} />
        </div>
      </div>

      <div className="bg-slate-700/30 rounded-lg p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-semibold text-slate-400">Metrics</h4>
          <EIntraMethodBadge
            method={exp.e_intra_method}
            source={eIntraProvenance}
            scope="e_intra"
          />
        </div>
        <MetricsTable metrics={metrics} />
      </div>

      <div className="bg-slate-700/30 rounded-lg p-3">
        <h4 className="text-xs font-semibold text-slate-400 mb-2">3D Structure</h4>
        <MoleculeViewer expId={expId} viewerHeight="h-56" />
      </div>
    </div>
  )
}

export default DynamicsExperimentDetail
