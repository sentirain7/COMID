import { useState } from 'react'
import StatusPanel from './StatusPanel'
import ExperimentQueuePanel from './ExperimentQueuePanel'
import DensityChart from './Charts/DensityChart'
import GPUUtilizationChart from './Charts/GPUUtilizationChart'
import CEDChart from './Charts/CEDChart'
import {
  useQueueStatsLive,
  useExperiments,
  useGPUStats,
  useRunningJobs,
  useCEDByAdditive,
  useExperimentEvents,
} from '../hooks/useApi'

function Dashboard() {
  const ffFilter = 'bulk_ff_gaff2'
  const [statusFilter, setStatusFilter] = useState('')

  const { data: stats, loading: statsLoading } = useQueueStatsLive()
  // Load full experiment queue for scrollable dashboard list.
  const { data: experiments, loading: expLoading, execute: refreshExperiments } = useExperiments({
    limit: 10000,
    status: statusFilter || undefined,
  })
  const { data: gpuStats, loading: gpuLoading } = useGPUStats()
  const { data: runningJobs, loading: jobsLoading } = useRunningJobs()
  const { data: cedData, loading: cedLoading } = useCEDByAdditive(ffFilter)
  const { eventsByExp } = useExperimentEvents()

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-slate-400 text-sm mt-1">
          Monitor simulation progress and review recent results.
        </p>
      </div>

      {/* Main Layout: Left Column (Status + Queue) | Right Column (GPU + Charts) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
        {/* Left Column: Current Status + Experiment Queue (stacked, fixed heights) */}
        <div className="lg:col-span-8 flex flex-col gap-4">
          <StatusPanel stats={stats} loading={statsLoading} />
          <div className="h-[760px]">
            <ExperimentQueuePanel
              experiments={experiments?.experiments || []}
              totalCount={experiments?.total_count}
              runningJobs={runningJobs?.jobs || []}
              experimentEvents={eventsByExp}
              loading={expLoading || jobsLoading}
              onRefresh={refreshExperiments}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
            />
          </div>
        </div>
        {/* Right Column: GPU + Charts — charts fill remaining height to align bottoms */}
        <div className="lg:col-span-4 flex flex-col gap-4 self-stretch">
          <div className="shrink-0">
            <GPUUtilizationChart gpuStats={gpuStats} loading={gpuLoading} />
          </div>
          <div className="flex-1 min-h-[200px]">
            <DensityChart />
          </div>
          <div className="flex-1 min-h-[200px]">
            <CEDChart data={cedData} loading={cedLoading} />
          </div>
        </div>
      </div>

    </div>
  )
}

export default Dashboard
