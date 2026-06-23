import { useState } from 'react'
import { RefreshCw, XCircle, RotateCcw, Trash2, AlertCircle, CheckCircle } from 'lucide-react'
import {
  useCancelJob,
  useDeleteAllCompletedJobs,
  useDeleteJob,
  useJobs,
  useQueueStats,
  useRetryJob,
} from '../hooks/useApi'
import clsx from 'clsx'
import { NotificationBanner, SelectionActionBar, StatusBadge, PriorityBadge } from './shared'
import { useNotification } from '../hooks/useNotification'

function Jobs() {
  const { data: stats, execute: refreshStats } = useQueueStats()
  const { data: jobsData, loading: jobsLoading, execute: refreshJobs } = useJobs()
  const deleteJobMutation = useDeleteJob()
  const cancelJobMutation = useCancelJob()
  const retryJobMutation = useRetryJob()
  const clearCompletedMutation = useDeleteAllCompletedJobs()
  const [selectedJobs, setSelectedJobs] = useState([])
  const [refreshing, setRefreshing] = useState(false)
  const { notification, notify, dismiss } = useNotification()

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await Promise.all([refreshStats?.(), refreshJobs?.()])
    } finally {
      setRefreshing(false)
    }
  }

  const handleClearCompleted = async () => {
    const completedCount = jobs.filter(j => j.status === 'completed').length
    if (completedCount === 0) {
      notify('info', 'No completed jobs to clear')
      return
    }
    if (!confirm(`Delete ${completedCount} completed job(s)?`)) return

    try {
      const result = await clearCompletedMutation.mutateAsync()
      notify('success', `Deleted ${result.deleted} completed job(s)`)
      handleRefresh()
    } catch (error) {
      console.error('Failed to clear completed jobs:', error)
      notify('error', `Failed to clear completed jobs: ${error.response?.data?.detail || error.message}`)
    }
  }

  // Get jobs from API or empty array
  const jobs = jobsData?.jobs || []

  const handleDelete = async (jobId) => {
    if (confirm(`Delete job ${jobId}?`)) {
      try {
        await deleteJobMutation.mutateAsync(jobId)
        await handleRefresh()
      } catch (error) {
        console.error('Failed to delete job:', error)
        notify('error', `Failed to delete job: ${error.response?.data?.detail || error.message}`)
      }
    }
  }

  const handleCancel = async (jobId) => {
    if (confirm(`Cancel job ${jobId}?`)) {
      try {
        await cancelJobMutation.mutateAsync(jobId)
        await handleRefresh()
      } catch (error) {
        console.error('Failed to cancel job:', error)
        notify('error', `Failed to cancel job: ${error.response?.data?.detail || error.message}`)
      }
    }
  }

  const handleBulkCancel = async () => {
    if (!confirm(`Cancel ${selectedJobs.length} job(s)?`)) return

    for (const jobId of selectedJobs) {
      try {
        await cancelJobMutation.mutateAsync(jobId)
      } catch (error) {
        console.error(`Failed to cancel ${jobId}:`, error)
      }
    }
    setSelectedJobs([])
    await handleRefresh()
  }

  const handleRetry = async (jobId) => {
    try {
      await retryJobMutation.mutateAsync(jobId)
    } catch (error) {
      console.error('Failed to retry job:', error)
    }
  }

  const toggleSelectJob = (jobId) => {
    setSelectedJobs((prev) =>
      prev.includes(jobId)
        ? prev.filter((id) => id !== jobId)
        : [...prev, jobId]
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Job Queue</h1>
          <p className="text-slate-400 text-sm mt-1">
            Manage simulation jobs and monitor queue status.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleClearCompleted}
            className="btn btn-secondary flex items-center gap-2"
            disabled={refreshing || jobs.filter(j => j.status === 'completed').length === 0}
          >
            <CheckCircle className="w-4 h-4" />
            Clear Completed
          </button>
          <button
            onClick={handleRefresh}
            className="btn btn-secondary flex items-center gap-2"
            disabled={refreshing}
          >
            <RefreshCw className={clsx('w-4 h-4', refreshing && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </div>

      <NotificationBanner notification={notification} onDismiss={dismiss} />

      {/* Queue Stats Summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="card p-4">
          <div className="text-2xl font-bold text-yellow-400">
            {stats?.total_pending ?? jobs.filter(j => j.status === 'pending').length}
          </div>
          <div className="text-sm text-slate-400">Pending</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-purple-400">
            {stats?.total_queued ?? jobs.filter(j => j.status === 'queued').length}
          </div>
          <div className="text-sm text-slate-400">Queued</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-blue-400">
            {stats?.total_running ?? jobs.filter(j => j.status === 'running').length}
          </div>
          <div className="text-sm text-slate-400">Running</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-green-400">
            {stats?.total_completed ?? jobs.filter(j => j.status === 'completed').length}
          </div>
          <div className="text-sm text-slate-400">Completed</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-red-400">
            {stats?.total_failed ?? jobs.filter(j => j.status === 'failed').length}
          </div>
          <div className="text-sm text-slate-400">Failed</div>
        </div>
      </div>

      {/* Jobs Table */}
      <div className="card">
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr className="text-center">
                <th className="w-10">
                  <input
                    type="checkbox"
                    className="w-4 h-4 rounded bg-slate-700 border-slate-600"
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedJobs(jobs.map((j) => j.job_id))
                      } else {
                        setSelectedJobs([])
                      }
                    }}
                  />
                </th>
                <th>Job ID</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Tier</th>
                <th>Material</th>
                <th>Atoms</th>
                <th>Temp (K)</th>
                <th>Progress</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 && (
                <tr>
                  <td colSpan={11} className="text-center py-12 text-slate-400">
                    {jobsLoading ? 'Loading jobs...' : 'No jobs in queue'}
                  </td>
                </tr>
              )}
              {jobs.map((job) => (
                <tr key={job.job_id} className="text-center">
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedJobs.includes(job.job_id)}
                      onChange={() => toggleSelectJob(job.job_id)}
                      className="w-4 h-4 rounded bg-slate-700 border-slate-600"
                    />
                  </td>
                  <td className="font-mono text-sm">{job.job_id}</td>
                  <td>
                    <div className="flex justify-center">
                      <StatusBadge status={job.status} />
                    </div>
                  </td>
                  <td>
                    <div className="flex justify-center">
                      <PriorityBadge priority={job.priority} />
                    </div>
                  </td>
                  <td className="capitalize">{job.tier}</td>
                  <td>{job.material_id}</td>
                  <td>{job.target_atoms ? (job.target_atoms / 1000).toFixed(0) + 'k' : '-'}</td>
                  <td>{job.temperature_k || '-'}</td>
                  <td>
                    {job.status === 'running' && job.progress !== undefined ? (
                      <div className="flex items-center justify-center gap-2">
                        <div className="w-20 h-2 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 transition-all duration-300"
                            style={{ width: `${job.progress}%` }}
                          />
                        </div>
                        <span className="text-sm text-slate-400">
                          {job.progress}%
                        </span>
                      </div>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="text-slate-400 text-sm">
                    {job.created_at ? new Date(job.created_at).toLocaleTimeString() : '-'}
                  </td>
                  <td>
                    <div className="flex items-center justify-center gap-1">
                      {job.status === 'running' && (
                        <button
                          onClick={() => handleCancel(job.job_id)}
                          className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded"
                          title="Cancel"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                      )}
                      {job.status === 'queued' && (
                        <button
                          onClick={() => handleCancel(job.job_id)}
                          className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded"
                          title="Cancel"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                      )}
                      {job.status === 'failed' && (
                        <button
                          onClick={() => handleRetry(job.job_id)}
                          className="p-1.5 text-slate-400 hover:text-blue-400 hover:bg-slate-700 rounded"
                          title="Retry"
                        >
                          <RotateCcw className="w-4 h-4" />
                        </button>
                      )}
                      {['completed', 'failed', 'cancelled'].includes(job.status) && (
                        <button
                          onClick={() => handleDelete(job.job_id)}
                          className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Failed Jobs Alert */}
      {jobs.filter((j) => j.status === 'failed').length > 0 && (
        <div className="card p-4 bg-red-500/10 border-red-500/30">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-medium text-red-400">Failed Jobs</h3>
              <p className="text-sm text-slate-300 mt-1">
                {jobs.filter((j) => j.status === 'failed').length} job(s) have
                failed. Review the error messages and retry if needed.
              </p>
            </div>
          </div>
        </div>
      )}

      <SelectionActionBar
        count={selectedJobs.length}
        onDeselect={() => setSelectedJobs([])}
        actions={
          <button
            onClick={handleBulkCancel}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-red-500/20 text-red-400 hover:bg-red-500/30"
          >
            <XCircle className="w-3 h-3" />
            Bulk Stop
          </button>
        }
      />
    </div>
  )
}

export default Jobs
