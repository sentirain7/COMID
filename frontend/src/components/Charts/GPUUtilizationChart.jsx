import { useMemo } from 'react'

/**
 * GPU Status Chart Component
 * Shows simple Available/Busy status for each GPU
 */
function GPUUtilizationChart({ gpuStats, loading }) {
  const { gpus, isError } = useMemo(() => {
    if (!gpuStats) {
      return { gpus: [], isError: true }
    }
    if (!Array.isArray(gpuStats.gpus) || gpuStats.gpus.length === 0) {
      return { gpus: [], isError: false }
    }
    // Filter out offline GPUs
    const onlineGpus = gpuStats.gpus.filter(gpu => gpu.status !== 'offline')
    return {
      gpus: onlineGpus,
      isError: false,
    }
  }, [gpuStats])


  if (loading) {
    return (
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <h3 className="text-base font-semibold text-white mb-3">GPU Status</h3>
        <div className="animate-pulse space-y-3">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-6 bg-slate-700 rounded" />
          ))}
        </div>
      </div>
    )
  }

  // Error state
  if (isError) {
    return (
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <h3 className="text-base font-semibold text-white mb-3">GPU Status</h3>
        <div className="text-slate-500 text-sm py-4 text-center">
          Unable to fetch GPU status
        </div>
      </div>
    )
  }

  // No GPUs available
  if (gpus.length === 0) {
    return (
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <h3 className="text-base font-semibold text-white mb-3">GPU Status</h3>
        <div className="text-slate-500 text-sm py-4 text-center">
          No GPUs detected
        </div>
      </div>
    )
  }

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <h3 className="text-base font-semibold text-white mb-3">GPU Status</h3>

      <div className="grid grid-cols-2 gap-2">
        {gpus.map((gpu) => {
          const isBusy = gpu.status === 'busy'

          return (
            <div key={gpu.id} className="flex items-center justify-between px-2 py-1.5 rounded border border-slate-700 bg-slate-750">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className={`w-2 h-2 rounded-full shrink-0 ${
                  isBusy ? 'bg-amber-400' : 'bg-emerald-400'
                }`} />
                <span className="text-slate-300 text-xs font-mono truncate">
                  GPU {gpu.id}
                </span>
                <span className="text-slate-500 text-xs">{gpu.utilization}%</span>
              </div>
              <span className={`text-xs font-medium px-1.5 py-0.5 rounded shrink-0 ${
                isBusy
                  ? 'bg-amber-900/50 text-amber-400'
                  : 'bg-emerald-900/50 text-emerald-400'
              }`}>
                {isBusy ? 'Busy' : 'Avail'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default GPUUtilizationChart
