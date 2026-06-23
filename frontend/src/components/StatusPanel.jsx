import { Layers, Clock, Hammer, Play, CheckCircle, XCircle, Ban, AlertCircle, Loader2 } from 'lucide-react'
import clsx from 'clsx'

function StageCard({ name, count, icon: Icon, color, loading }) {
  const colorClasses = {
    slate: 'bg-slate-500/20 text-slate-300 border-slate-500/30',
    yellow: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    indigo: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
    blue: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    green: 'bg-green-500/20 text-green-400 border-green-500/30',
    red: 'bg-red-500/20 text-red-400 border-red-500/30',
    gray: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    orange: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  }

  const iconColorClasses = {
    slate: 'bg-slate-500',
    yellow: 'bg-yellow-500',
    indigo: 'bg-indigo-500',
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    red: 'bg-red-500',
    gray: 'bg-gray-500',
    orange: 'bg-orange-500',
  }

  return (
    <div className={clsx(
      'flex-1 min-w-[60px] px-2 py-1 rounded-lg border transition-all hover:scale-105 flex items-center justify-center gap-2',
      colorClasses[color] || colorClasses.blue
    )}>
      <div className={clsx(
        'w-4 h-4 rounded flex items-center justify-center flex-shrink-0',
        iconColorClasses[color] || iconColorClasses.blue
      )}>
        <Icon className="w-2.5 h-2.5 text-white" />
      </div>
      <span className="text-[10px] font-medium uppercase tracking-wide opacity-80">{name}</span>
      {loading ? (
        <Loader2 className="w-4 h-4 animate-spin opacity-50" />
      ) : (
        <span className="text-lg font-bold">{count}</span>
      )}
    </div>
  )
}

function StatusPanel({ stats, loading }) {
  const pendingCount = stats?.total_pending ?? 0
  const queuedCount = stats?.total_queued ?? 0
  const buildingCount = stats?.building ?? 0
  const readyCount = stats?.ready ?? 0
  const runningCount = stats?.total_running ?? 0
  const completedCount = stats?.total_completed ?? 0
  const failedCount = stats?.total_failed ?? 0
  const cancelledCount = stats?.total_cancelled ?? 0
  const allCount = pendingCount + queuedCount + buildingCount + readyCount + runningCount + completedCount + failedCount + cancelledCount

  // Mirror Experiment Queue filter buckets (matches StatusBadge SSOT colors)
  const stages = [
    { name: 'Total', count: allCount, icon: Layers, color: 'slate' },
    { name: 'Pending', count: pendingCount, icon: Clock, color: 'yellow' },
    { name: 'Queued', count: queuedCount, icon: Clock, color: 'blue' },
    { name: 'Building', count: buildingCount, icon: Hammer, color: 'indigo' },
    { name: 'Ready', count: readyCount, icon: AlertCircle, color: 'blue' },
    { name: 'Running', count: runningCount, icon: Play, color: 'green' },
    { name: 'Completed', count: completedCount, icon: CheckCircle, color: 'gray' },
    { name: 'Failed', count: failedCount, icon: XCircle, color: 'red' },
    { name: 'Cancelled', count: cancelledCount, icon: Ban, color: 'gray' },
  ]

  return (
    <div className="card p-3 h-full flex flex-col">
      <h3 className="text-sm font-semibold text-white mb-2">Current Status</h3>

      <div className="flex items-center justify-between gap-1.5 flex-wrap">
        {stages.map((stage) => (
          <StageCard key={stage.name} {...stage} loading={loading} />
        ))}
      </div>
    </div>
  )
}

export default StatusPanel
