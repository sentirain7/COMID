import { useState, useMemo, useCallback, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, RotateCcw, StopCircle, Trash2 } from 'lucide-react'
import { NotificationBanner, SelectionActionBar } from './shared'
import {
  useBatchCancelExperiments,
  useBatchDeleteExperiments,
  useBatchRetryExperiments,
  useCancelExperiment,
  useDeleteExperiment,
  useRetryExperiment,
} from '../hooks/useApi'
import { useNotification } from '../hooks/useNotification'
import ExperimentRow from './experiment-queue/ExperimentRow'

const CANCELABLE_STATUSES = new Set(['pending', 'queued', 'building', 'ready', 'running', 'analyzing'])
const DELETABLE_STATUSES = new Set(['ready', 'completed', 'failed', 'cancelled', 'timeout'])
const RETRYABLE_STATUSES = new Set(['failed', 'cancelled', 'timeout'])

const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'queued', label: 'Queued' },
  { value: 'building', label: 'Building' },
  { value: 'ready', label: 'Ready' },
  { value: 'running', label: 'Running' },
  { value: 'analyzing', label: 'Analyzing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'timeout', label: 'Timeout' },
]

/**
 * ExperimentQueuePanel - Integrated experiment queue view for Dashboard.
 *
 * Orchestrates state management, batch operations, data merging/sorting,
 * and delegates row rendering to ExperimentRow.
 */
function ExperimentQueuePanel({
  experiments = [],
  totalCount,
  runningJobs = [],
  experimentEvents = {},
  loading = false,
  onRefresh,
  statusFilter = '',
  onStatusFilterChange,
}) {
  const [actionLoading, setActionLoading] = useState(null) // exp_id being actioned
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [batchLoading, setBatchLoading] = useState(false)
  const deleteMutation = useDeleteExperiment()
  const cancelMutation = useCancelExperiment()
  const retryMutation = useRetryExperiment()
  const batchCancelMutation = useBatchCancelExperiments()
  const batchDeleteMutation = useBatchDeleteExperiments()
  const batchRetryMutation = useBatchRetryExperiments()
  const { notification, notify, dismiss } = useNotification()

  // Selection helpers
  const toggleSelect = useCallback((expId) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(expId)) next.delete(expId)
      else next.add(expId)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback((allIds) => {
    setSelectedIds(prev => prev.size === allIds.length ? new Set() : new Set(allIds))
  }, [])

  // Handle cancel experiment
  const handleCancel = async (expId) => {
    if (!confirm(`Stop experiment ${expId}?`)) return
    setActionLoading(expId)
    try {
      await cancelMutation.mutateAsync(expId)
      onRefresh?.()
    } catch (error) {
      notify('error', `Stop failed: ${error.response?.data?.detail || error.message}`)
    } finally {
      setActionLoading(null)
    }
  }

  // Handle delete experiment
  const handleDelete = async (expId) => {
    if (!confirm(`Delete experiment ${expId}? This action cannot be undone.`)) return
    setActionLoading(expId)
    try {
      await deleteMutation.mutateAsync(expId)
      onRefresh?.()
    } catch (error) {
      notify('error', `Delete failed: ${error.response?.data?.detail || error.message}`)
    } finally {
      setActionLoading(null)
    }
  }

  // Handle retry experiment (checkpoint-first)
  const handleRetry = async (expId) => {
    if (!confirm(`Retry experiment ${expId}?`)) return
    setActionLoading(expId)
    try {
      await retryMutation.mutateAsync(expId)
      notify('info', `Retry submitted: ${expId}`)
      onRefresh?.()
    } catch (error) {
      notify('error', `Retry failed: ${error.response?.data?.detail || error.message}`)
    } finally {
      setActionLoading(null)
    }
  }

  // Batch cancel handler
  const handleBatchCancel = async () => {
    const targets = [...selectedIds].filter(id => {
      const exp = experiments.find(e => e.exp_id === id)
      return exp && CANCELABLE_STATUSES.has(exp.status)
    })
    if (targets.length === 0) {
      notify('info', 'No cancelable experiments in selection')
      return
    }
    if (!confirm(`Stop ${targets.length} experiments?`)) return
    setBatchLoading(true)
    try {
      const result = await batchCancelMutation.mutateAsync(targets)
      setSelectedIds(new Set())
      onRefresh?.()
      notify('success', `${result.succeeded} stopped, ${result.skipped} skipped, ${result.failed} failed`)
    } catch (error) {
      notify('error', `Bulk stop failed: ${error.response?.data?.detail || error.message}`)
    } finally {
      setBatchLoading(false)
    }
  }

  // Batch delete handler
  const handleBatchDelete = async () => {
    const targets = [...selectedIds].filter(id => {
      const exp = experiments.find(e => e.exp_id === id)
      return exp && DELETABLE_STATUSES.has(exp.status)
    })
    if (targets.length === 0) {
      notify('info', 'No deletable experiments in selection')
      return
    }
    if (!confirm(`Delete ${targets.length} experiments? This action cannot be undone.`)) return
    setBatchLoading(true)
    try {
      const result = await batchDeleteMutation.mutateAsync(targets)
      setSelectedIds(new Set())
      onRefresh?.()
      notify('success', `${result.succeeded} deleted, ${result.skipped} skipped, ${result.failed} failed`)
    } catch (error) {
      notify('error', `Bulk delete failed: ${error.response?.data?.detail || error.message}`)
    } finally {
      setBatchLoading(false)
    }
  }

  // Batch retry handler
  const handleBatchRetry = async () => {
    const targets = [...selectedIds].filter(id => {
      const exp = experiments.find(e => e.exp_id === id)
      return exp && RETRYABLE_STATUSES.has(exp.status)
    })
    if (targets.length === 0) {
      notify('info', 'No retryable experiments in selection')
      return
    }
    if (!confirm(`Retry ${targets.length} experiments?`)) return
    setBatchLoading(true)
    try {
      const result = await batchRetryMutation.mutateAsync(targets)
      setSelectedIds(new Set())
      onRefresh?.()
      notify('success', `${result.succeeded} retried, ${result.skipped} skipped, ${result.failed} failed`)
    } catch (error) {
      notify('error', `Bulk retry failed: ${error.response?.data?.detail || error.message}`)
    } finally {
      setBatchLoading(false)
    }
  }

  // Selected counts for toolbar
  const selectedCancelableCount = [...selectedIds].filter(id => {
    const exp = experiments.find(e => e.exp_id === id)
    return exp && CANCELABLE_STATUSES.has(exp.status)
  }).length
  const selectedDeletableCount = [...selectedIds].filter(id => {
    const exp = experiments.find(e => e.exp_id === id)
    return exp && DELETABLE_STATUSES.has(exp.status)
  }).length
  const selectedRetryableCount = [...selectedIds].filter(id => {
    const exp = experiments.find(e => e.exp_id === id)
    return exp && RETRYABLE_STATUSES.has(exp.status)
  }).length

  // Merge experiments with running job progress data
  // DB status is SSOT - only show progress for experiments that are 'running' in DB
  const mergedData = useMemo(() => {
    const runningJobsMap = new Map()
    runningJobs.forEach(job => {
      if (job.exp_id) {
        runningJobsMap.set(job.exp_id, job)
      }
    })

    return experiments.map(exp => {
      const runningJob = runningJobsMap.get(exp.exp_id)
      // DB status is SSOT: only show progress when DB says 'running' AND we have job data
      const isActuallyRunning = exp.status === 'running' && runningJob
      const isBuilding = exp.status === 'building' && runningJob

      return {
        ...exp,
        displayStatus: exp.status,
        timelineEvents: experimentEvents?.[exp.exp_id] || [],
        buildPhase: isBuilding ? runningJob?.build_phase : null,
        buildPhaseLabel: isBuilding ? runningJob?.build_phase_label : null,
        telemetryStale: exp.status === 'running' && (!runningJob || runningJob?.telemetry_stale),
        telemetryAgeSec: runningJob?.telemetry_age_sec ?? null,
        progress: isActuallyRunning ? (runningJob?.progress || 0) :
                  (exp.status === 'completed' ? 100 : 0),
        currentStep: isActuallyRunning ? (runningJob?.current_step || 0) : 0,
        totalSteps: isActuallyRunning ? (runningJob?.total_steps || 0) : 0,
        elapsed: isActuallyRunning ? runningJob?.elapsed : null,
        eta: isActuallyRunning ? runningJob?.eta : null,
        gpuId: exp.gpu_id_allocated ?? (isActuallyRunning ? runningJob?.gpu_id : null),
        temperature: isActuallyRunning ? runningJob?.temperature : null,
        pressure: isActuallyRunning ? runningJob?.pressure : null,
        density: isActuallyRunning ? runningJob?.density : null,
        energy: isActuallyRunning ? runningJob?.energy : null,
        currentStage: isActuallyRunning ? runningJob?.current_stage : null,
        stageProgress: isActuallyRunning ? runningJob?.stage_progress : null,
        stageStep: isActuallyRunning ? (runningJob?.stage_step || 0) : 0,
        stageTotalSteps: isActuallyRunning ? (runningJob?.stage_total_steps || 0) : 0,
        stagePercent: isActuallyRunning ? (runningJob?.stage_percent || 0) : 0,
        wallTimeSeconds: Number.isFinite(Number(exp.wall_time_seconds))
          ? Number(exp.wall_time_seconds)
          : null,
        pipelineElapsedSeconds: (() => {
          const fromJob = runningJob?.pipeline_elapsed_seconds
          const fromExp = exp.pipeline_elapsed_seconds
          const value = fromJob ?? fromExp
          return Number.isFinite(Number(value)) ? Number(value) : null
        })(),
        buildProgressPercent: isBuilding
          ? (Number.isFinite(Number(runningJob?.build_progress_percent))
              ? Number(runningJob?.build_progress_percent)
              : null)
          : null,
      }
    })
  }, [experiments, runningJobs, experimentEvents])

  // Visible experiment IDs - used to prune hidden selections when filter changes
  const visibleIds = useMemo(
    () => new Set(experiments.map(e => e.exp_id)),
    [experiments]
  )

  // Auto-prune selectedIds when visible experiments change (filter applied)
  useEffect(() => {
    setSelectedIds(prev => {
      const pruned = new Set([...prev].filter(id => visibleIds.has(id)))
      // Only update if actually changed to avoid unnecessary re-renders
      return pruned.size === prev.size ? prev : pruned
    })
  }, [visibleIds])

  // Visible selected count - for header checkbox and toolbar
  const visibleSelectedCount = useMemo(
    () => mergedData.filter(exp => selectedIds.has(exp.exp_id)).length,
    [mergedData, selectedIds]
  )

  // Create job number mapping based on creation time (ascending order)
  const jobNumberMap = useMemo(() => {
    const sorted = [...mergedData].sort((a, b) =>
      new Date(a.created_at) - new Date(b.created_at)
    )
    const map = new Map()
    sorted.forEach((exp, idx) => {
      map.set(exp.exp_id, idx + 1)
    })
    return map
  }, [mergedData])

  // Sort for display: running first, then pending, then completed, then failed
  const sortedData = useMemo(() => {
    const statusOrder = { building: 0, ready: 1, running: 2, pending: 3, queued: 3, completed: 4, failed: 5 }
    return [...mergedData].sort((a, b) => {
      const orderA = statusOrder[a.displayStatus] ?? 5
      const orderB = statusOrder[b.displayStatus] ?? 5
      if (orderA !== orderB) return orderA - orderB
      return new Date(a.created_at) - new Date(b.created_at)
    })
  }, [mergedData])

  return (
    <div className="card h-full flex flex-col">
      {/* Header */}
      <div className="card-header flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-white">Experiment Queue</h2>
          <span className="text-sm text-slate-400">
            ({totalCount ?? mergedData.length} total)
          </span>
        </div>
      </div>

      <NotificationBanner notification={notification} onDismiss={dismiss} />

      <div className="flex flex-col flex-grow min-h-0">
          {/* Experiment Table */}
          <div className="overflow-auto flex-grow">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
              </div>
            ) : (
              <table className="table table-fixed">
                <thead className="sticky top-0 bg-slate-800 z-10">
                  <tr className="text-center">
                    <th className="w-[32px] pl-2 pr-0">
                      <input
                        type="checkbox"
                        checked={sortedData.length > 0 && visibleSelectedCount === sortedData.length}
                        ref={el => {
                          if (el) el.indeterminate = visibleSelectedCount > 0 && visibleSelectedCount < sortedData.length
                        }}
                        onChange={() => toggleSelectAll(sortedData.map(e => e.exp_id))}
                        className="w-3.5 h-3.5 rounded border-slate-500 bg-slate-700 text-blue-500 cursor-pointer"
                      />
                    </th>
                    <th className="w-[40px] pl-1 pr-1">#</th>
                    <th className="w-[168px] px-0">
                      <div className="flex items-center justify-between">
                        <span>Experiment ID</span>
                        {onStatusFilterChange && (
                          <select
                            value={statusFilter}
                            onChange={(e) => onStatusFilterChange(e.target.value)}
                            className="bg-slate-700 border border-slate-600 rounded px-1 py-0.5 text-[10px] text-slate-200 w-[68px] cursor-pointer focus:outline-none focus:border-blue-500"
                          >
                            {STATUS_OPTIONS.map(opt => (
                              <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    </th>
                    <th className="w-[86px] px-0.5">Status</th>
                    <th className="w-[50px] px-1">GPU</th>
                    <th className="w-[110px] px-0.5">Progress</th>
                    <th className="w-[90px] px-0">
                      <div className="leading-tight">
                        <div>Temperature</div>
                        <div>Density</div>
                      </div>
                    </th>
                    <th className="w-[82px] px-0">Created</th>
                    <th className="w-[92px] px-1">Completed</th>
                    <th className="w-[96px] px-1">
                      <div className="leading-tight">
                        <div>Calculation</div>
                        <div>Elapsed</div>
                      </div>
                    </th>
                    <th className="w-[80px] px-1">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedData.map((exp) => (
                    <ExperimentRow
                      key={exp.exp_id}
                      exp={exp}
                      jobNumber={jobNumberMap.get(exp.exp_id)}
                      selected={selectedIds.has(exp.exp_id)}
                      actionLoading={actionLoading === exp.exp_id}
                      onSelect={toggleSelect}
                      onCancel={handleCancel}
                      onDelete={handleDelete}
                      onRetry={handleRetry}
                    />
                  ))}
                  {sortedData.length === 0 && (
                    <tr>
                      <td colSpan={11} className="text-center py-8 text-slate-400">
                        No experiments in queue
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>

          {/* View All Link */}
          {(totalCount ?? 0) > mergedData.length && (
            <div className="px-6 py-3 border-t border-slate-700 text-center flex-shrink-0">
              <Link
                to="/experiments"
                className="text-sm text-blue-400 hover:text-blue-300"
              >
                View all {totalCount} experiments
              </Link>
            </div>
          )}
        </div>

      <SelectionActionBar
        count={visibleSelectedCount}
        onDeselect={() => setSelectedIds(new Set())}
        actions={<>
          {selectedRetryableCount > 0 && (
            <button
              onClick={handleBatchRetry}
              disabled={batchLoading}
              className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 disabled:opacity-50"
            >
              <RotateCcw className="w-3 h-3" />
              Bulk Retry ({selectedRetryableCount})
            </button>
          )}
          {selectedCancelableCount > 0 && (
            <button
              onClick={handleBatchCancel}
              disabled={batchLoading}
              className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-orange-500/20 text-orange-400 hover:bg-orange-500/30 disabled:opacity-50"
            >
              <StopCircle className="w-3 h-3" />
              Bulk Stop ({selectedCancelableCount})
            </button>
          )}
          {selectedDeletableCount > 0 && (
            <button
              onClick={handleBatchDelete}
              disabled={batchLoading}
              className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50"
            >
              <Trash2 className="w-3 h-3" />
              Bulk Delete ({selectedDeletableCount})
            </button>
          )}
        </>}
      />
    </div>
  )
}

export default ExperimentQueuePanel
