import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Search, Filter, RefreshCw, Trash2, XCircle, RotateCcw, Download } from 'lucide-react'
import { useBatchCancelExperiments, useBatchDeleteExperiments, useExperiments, useRetryExperiment } from '../hooks/useApi'
import { exportExperiments, getExportFormats } from '../api/client'
import clsx from 'clsx'
import { NotificationBanner, SelectionActionBar, StatusBadge, TierBadge } from './shared'
import { useNotification } from '../hooks/useNotification'

function Experiments() {
  const [statusFilter, setStatusFilter] = useState('')
  const [tierFilter, setTierFilter] = useState('')
  const [search, setSearch] = useState('')
  const [selectedExperiments, setSelectedExperiments] = useState([])
  const [exporting, setExporting] = useState(false)
  const [xlsxAvailable, setXlsxAvailable] = useState(false)
  const { notification, notify, dismiss } = useNotification()

  useEffect(() => {
    getExportFormats()
      .then((data) => {
        setXlsxAvailable(data?.formats?.xlsx?.available ?? false)
      })
      .catch(() => setXlsxAvailable(false))
  }, [])
  const retryMutation = useRetryExperiment()

  const handleExport = async (format) => {
    setExporting(true)
    try {
      await exportExperiments({
        format,
        status: statusFilter || undefined,
        tier: tierFilter || undefined,
      })
      notify('success', `Exported experiments as ${format.toUpperCase()}`)
    } catch (error) {
      console.error('Export failed:', error)
      notify('error', `Export failed: ${error.message}`)
    } finally {
      setExporting(false)
    }
  }

  const { data, loading, execute: refresh } = useExperiments({
    status: statusFilter || undefined,
    tier: tierFilter || undefined,
  })

  // Get experiments from API or empty array
  const experiments = data?.experiments || []

  // Filter experiments
  const filteredExperiments = experiments.filter((exp) => {
    if (search && !exp.exp_id.toLowerCase().includes(search.toLowerCase())) {
      return false
    }
    return true
  })
  const selectedSet = new Set(selectedExperiments)

  const handleRetry = async (expId) => {
    if (!confirm(`Retry experiment ${expId}?`)) return
    try {
      await retryMutation.mutateAsync(expId)
      notify('info', `Retry submitted for ${expId}`)
      refresh()
    } catch (error) {
      console.error('Retry failed:', error)
      notify('error', `Failed to retry: ${error.response?.data?.detail || error.message}`)
    }
  }

  const canCancelStatus = (status) => ['pending', 'queued', 'building', 'ready', 'running', 'analyzing'].includes(status)
  const canDeleteStatus = (status) => ['ready', 'completed', 'failed', 'cancelled', 'timeout'].includes(status)

  const toggleSelectExperiment = (expId) => {
    setSelectedExperiments((prev) =>
      prev.includes(expId)
        ? prev.filter((id) => id !== expId)
        : [...prev, expId]
    )
  }

  const handleSelectAllVisible = (checked) => {
    if (checked) {
      setSelectedExperiments(filteredExperiments.map((exp) => exp.exp_id))
      return
    }
    setSelectedExperiments([])
  }

  const batchCancelMutation = useBatchCancelExperiments()
  const batchDeleteMutation = useBatchDeleteExperiments()

  const handleBulkCancel = async () => {
    const targetIds = filteredExperiments
      .filter((exp) => selectedSet.has(exp.exp_id) && canCancelStatus(exp.status))
      .map((exp) => exp.exp_id)
    if (targetIds.length === 0) {
      notify('info', 'No selected experiments can be cancelled')
      return
    }
    if (!confirm(`Cancel ${targetIds.length} selected experiment(s)?`)) return

    try {
      const result = await batchCancelMutation.mutateAsync(targetIds)
      setSelectedExperiments([])
      refresh()
      notify('success', `Cancelled ${result.succeeded}/${result.total}. ${result.failed} failed.`)
    } catch (error) {
      notify('error', `Batch cancel failed: ${error.response?.data?.detail || error.message}`)
    }
  }

  const handleBulkDelete = async () => {
    const targetIds = filteredExperiments
      .filter((exp) => selectedSet.has(exp.exp_id) && canDeleteStatus(exp.status))
      .map((exp) => exp.exp_id)
    if (targetIds.length === 0) {
      notify('info', 'No selected experiments can be deleted')
      return
    }
    if (!confirm(`Delete ${targetIds.length} selected experiment(s)? This cannot be undone.`)) return

    try {
      const result = await batchDeleteMutation.mutateAsync(targetIds)
      setSelectedExperiments([])
      refresh()
      notify('success', `Deleted ${result.succeeded}/${result.total}. ${result.failed} failed.`)
    } catch (error) {
      notify('error', `Batch delete failed: ${error.response?.data?.detail || error.message}`)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Experiments</h1>
          <p className="text-slate-400 text-sm mt-1">
            View and manage Binder Cell simulation runs.
          </p>
        </div>
        <Link to="/single-job/binder-cell" className="btn btn-primary flex items-center gap-2">
          <Plus className="w-5 h-5" />
          Binder Cell
        </Link>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="p-4">
          <NotificationBanner notification={notification} onDismiss={dismiss} />
          <div className="flex flex-wrap items-center gap-4">
            {/* Search */}
            <div className="flex-1 min-w-[200px]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search by experiment ID..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="input pl-10"
                />
              </div>
            </div>

            {/* Status Filter */}
            <div className="flex items-center gap-2">
              <Filter className="w-5 h-5 text-slate-400" />
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="input w-40"
              >
                <option value="">All Status</option>
                <option value="pending">Pending</option>
                <option value="queued">Queued</option>
                <option value="running">Running</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>

            {/* Tier Filter */}
            <select
              value={tierFilter}
              onChange={(e) => setTierFilter(e.target.value)}
              className="input w-40"
            >
              <option value="">All Tiers</option>
              <option value="screening">Screening</option>
              <option value="confirm">Confirm</option>
              <option value="viscosity">Viscosity</option>
              <option value="validation">Validation</option>
            </select>

            {/* Refresh */}
            <button
              onClick={() => refresh()}
              className="btn btn-secondary flex items-center gap-2"
              disabled={loading}
            >
              <RefreshCw className={clsx('w-4 h-4', loading && 'animate-spin')} />
              Refresh
            </button>

            {/* Export */}
            <div className="relative group">
              <button
                className="btn btn-secondary flex items-center gap-2"
                disabled={exporting}
              >
                <Download className={clsx('w-4 h-4', exporting && 'animate-pulse')} />
                Export
              </button>
              <div className="absolute right-0 top-full mt-1 hidden group-hover:block bg-slate-700 rounded shadow-lg z-10 min-w-[100px]">
                <button
                  onClick={() => handleExport('csv')}
                  className="block w-full px-4 py-2 text-left text-sm text-slate-200 hover:bg-slate-600 rounded-t"
                  disabled={exporting}
                >
                  CSV
                </button>
                {xlsxAvailable && (
                  <button
                    onClick={() => handleExport('xlsx')}
                    className="block w-full px-4 py-2 text-left text-sm text-slate-200 hover:bg-slate-600 rounded-b"
                    disabled={exporting}
                  >
                    XLSX
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Experiments Table */}
      <div className="card">
        <div className="overflow-x-auto">
          <table className="table table-compact w-full">
            <thead>
              <tr className="text-center">
                <th className="w-10 px-2">
                  <input
                    type="checkbox"
                    className="w-5 h-5 rounded bg-slate-700 border-slate-500 border-2 cursor-pointer accent-blue-500"
                    checked={
                      filteredExperiments.length > 0
                      && selectedExperiments.length === filteredExperiments.length
                    }
                    onChange={(e) => handleSelectAllVisible(e.target.checked)}
                    title="Select All"
                  />
                </th>
                <th className="min-w-[200px]">Experiment ID</th>
                <th className="w-24">Status</th>
                <th className="w-20">Tier</th>
                <th className="w-16">Temp</th>
                <th className="w-16">Atoms</th>
                <th className="w-20">Density</th>
                <th className="w-28">Started</th>
                <th className="w-20">Duration</th>
                <th className="w-16">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredExperiments.map((exp) => (
                <tr
                  key={exp.exp_id}
                  className={clsx(
                    'text-center',
                    exp.data_age === 'historical' && 'opacity-50',
                    exp.data_age === 'current_session' && 'bg-blue-500/5 border-l-2 border-l-blue-500',
                    selectedSet.has(exp.exp_id) && 'bg-blue-500/10'
                  )}
                >
                  <td className="px-2">
                    <input
                      type="checkbox"
                      checked={selectedSet.has(exp.exp_id)}
                      onChange={() => toggleSelectExperiment(exp.exp_id)}
                      className="w-5 h-5 rounded bg-slate-700 border-slate-500 border-2 cursor-pointer accent-blue-500"
                    />
                  </td>
                  <td>
                    <Link
                      to={`/experiments/${exp.exp_id}`}
                      className="text-blue-400 hover:text-blue-300 font-mono text-xs"
                    >
                      {exp.exp_id}
                    </Link>
                  </td>
                  <td>
                    <div className="flex justify-center">
                      <StatusBadge status={exp.status} />
                    </div>
                  </td>
                  <td>
                    <div className="flex justify-center">
                      <TierBadge tier={exp.run_tier} />
                    </div>
                  </td>
                  <td className="text-sm">{exp.temperature_k || '-'}</td>
                  <td className="text-sm">
                    {exp.target_atoms
                      ? `${(exp.target_atoms / 1000).toFixed(0)}k`
                      : '-'}
                  </td>
                  <td className="text-sm">
                    {exp.metrics?.density
                      ? exp.metrics.density.toFixed(3)
                      : '-'}
                  </td>
                  <td className="text-slate-400 text-xs whitespace-nowrap">
                    {exp.started_at
                      ? new Date(exp.started_at).toLocaleString('ko-KR', {
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit'
                        })
                      : '-'}
                  </td>
                  <td className="text-slate-400 text-xs whitespace-nowrap">
                    {exp.wall_time_seconds
                      ? exp.wall_time_seconds >= 3600
                        ? `${(exp.wall_time_seconds / 3600).toFixed(1)}h`
                        : exp.wall_time_seconds >= 60
                          ? `${(exp.wall_time_seconds / 60).toFixed(0)}m`
                          : `${exp.wall_time_seconds.toFixed(0)}s`
                      : '-'}
                  </td>
                  <td>
                    <div className="flex items-center justify-center gap-1">
                      <Link
                        to={`/experiments/${exp.exp_id}`}
                        className="btn btn-secondary btn-sm"
                      >
                        View
                      </Link>

                      {/* Retry button for failed */}
                      {exp.status === 'failed' && (
                        <button
                          onClick={() => handleRetry(exp.exp_id)}
                          className="p-1.5 text-slate-400 hover:text-blue-400 hover:bg-slate-700 rounded"
                          title="Retry"
                        >
                          <RotateCcw className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {filteredExperiments.length === 0 && (
                <tr>
                  <td colSpan={10} className="text-center py-12 text-slate-400">
                    {loading ? 'Loading experiments...' : 'No experiments found'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <SelectionActionBar
        count={selectedExperiments.length}
        onDeselect={() => setSelectedExperiments([])}
        actions={<>
          <button
            onClick={handleBulkCancel}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-orange-500/20 text-orange-400 hover:bg-orange-500/30"
          >
            <XCircle className="w-3 h-3" />
            Bulk Stop
          </button>
          <button
            onClick={handleBulkDelete}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-red-500/20 text-red-400 hover:bg-red-500/30"
          >
            <Trash2 className="w-3 h-3" />
            Bulk Delete
          </button>
        </>}
      />
    </div>
  )
}

export default Experiments
