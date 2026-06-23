import { useState, useMemo } from 'react'
import { Trash2, ChevronRight, Search } from 'lucide-react'
import { useDeleteExperiment, useExperiments, useExperimentFilterOptions } from '../hooks/useApi'
import clsx from 'clsx'
import { DeleteModal, NotificationBanner, StatusBadge } from './shared/index'
import { useNotification } from '../hooks/useNotification'
import PageHeader from './shared/PageHeader'
import { HEADER_ACTION_BUTTON } from './shared/headerActionStyles'
import ScanDatabaseModal from './ScanDatabaseModal'
import { ROUTE_KEYS } from '../navigation/routeMeta'
import ExperimentDetail from './database/ExperimentDetail'
import { STATUS_FILTERS, TIER_FILTERS } from './database/config'

function BinderCellsPage() {
  const [selectedExpId, setSelectedExpId] = useState(null)
  const [deleteModal, setDeleteModal] = useState({ open: false, expId: null })
  const [selectedExperiments, setSelectedExperiments] = useState([])
  const [scanModalOpen, setScanModalOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [tierFilter, setTierFilter] = useState('')
  const [temperatureMin, setTemperatureMin] = useState('')
  const [temperatureMax, setTemperatureMax] = useState('')
  const [additiveTypeFilter, setAdditiveTypeFilter] = useState('')
  const { notification, notify, dismiss } = useNotification()
  const { data: filterOptions } = useExperimentFilterOptions()

  const filters = useMemo(() => {
    const f = { exclude_layered: true, study_type: 'bulk' }
    if (statusFilter) f.status = statusFilter
    if (tierFilter) f.tier = tierFilter
    if (temperatureMin !== '') f.temperature_min = Number(temperatureMin)
    if (temperatureMax !== '') f.temperature_max = Number(temperatureMax)
    if (additiveTypeFilter) f.additive_type = additiveTypeFilter
    return f
  }, [statusFilter, tierFilter, temperatureMin, temperatureMax, additiveTypeFilter])
  const { data, loading, execute: refresh } = useExperiments(filters)
  const deleteMutation = useDeleteExperiment()
  const selectedSet = new Set(selectedExperiments)

  const toggleSelectExperiment = (expId, e) => {
    e.stopPropagation()
    setSelectedExperiments((prev) =>
      prev.includes(expId)
        ? prev.filter((id) => id !== expId)
        : [...prev, expId]
    )
  }

  const handleSelectAll = (checked) => {
    if (checked) {
      setSelectedExperiments(visibleExperiments.map((exp) => exp.exp_id))
    } else {
      setSelectedExperiments([])
    }
  }

  const handleBulkDelete = async () => {
    if (selectedExperiments.length === 0) {
      notify('info', 'Select experiments to delete')
      return
    }
    if (!confirm(`Delete ${selectedExperiments.length} selected experiments?`)) return

    let failed = 0
    for (const expId of selectedExperiments) {
      try {
        await deleteMutation.mutateAsync(expId)
      } catch {
        failed += 1
      }
    }
    if (selectedExpId && selectedExperiments.includes(selectedExpId)) {
      setSelectedExpId(null)
    }
    setSelectedExperiments([])
    refresh()
    if (failed > 0) {
      notify('error', `${selectedExperiments.length - failed} deleted, ${failed} failed`)
    } else {
      notify('success', `${selectedExperiments.length} experiments deleted`)
    }
  }

  const experiments = data?.experiments || []
  const visibleExperiments = experiments

  const handleDelete = async () => {
    try {
      await deleteMutation.mutateAsync(deleteModal.expId)
      setDeleteModal({ open: false, expId: null })
      if (selectedExpId === deleteModal.expId) {
        setSelectedExpId(null)
      }
      refresh()
    } catch (error) {
      console.error('Delete failed:', error)
      notify('error', `Failed to delete: ${error.response?.data?.detail || error.message || 'Unknown error'}`)
    }
  }

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col">
      {/* Header */}
      <PageHeader
        routeKey={ROUTE_KEYS.BINDER_CELLS_DATABASE}
        subtitle="Browse binder-cell sources for layered-structure composition."
        className="mb-4"
      >
        <div className="flex items-center gap-2">
          <button
            onClick={() => setScanModalOpen(true)}
            className={HEADER_ACTION_BUTTON}
          >
            <Search className="w-4 h-4" />
            Scan Database
          </button>
        </div>
      </PageHeader>
      <NotificationBanner notification={notification} onDismiss={dismiss} />

      <ScanDatabaseModal open={scanModalOpen} onClose={() => { setScanModalOpen(false); refresh() }} />

      {/* Main content - Master-Detail Layout */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Left Panel - Experiment List (35%) */}
        <div className="w-[35%] flex flex-col card">
          <div className="p-3 border-b border-slate-700 space-y-3">
            <div className="flex items-center gap-2">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => { setStatusFilter(f.value); setSelectedExperiments([]) }}
                  className={clsx(
                    'px-2 py-0.5 rounded text-[11px] font-medium transition-colors',
                    statusFilter === f.value
                      ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            {/* Tier filter */}
            <div className="flex items-center gap-2">
              {TIER_FILTERS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => { setTierFilter(f.value); setSelectedExperiments([]) }}
                  className={clsx(
                    'px-2 py-0.5 rounded text-[11px] font-medium transition-colors',
                    tierFilter === f.value
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            {/* Temperature range + Additive type */}
            <div className="flex items-center gap-2">
              <label className="text-[11px] text-slate-400">T(K):</label>
              <input
                type="number"
                placeholder="Min"
                value={temperatureMin}
                onChange={(e) => setTemperatureMin(e.target.value)}
                className="w-16 px-1.5 py-0.5 rounded bg-slate-700 border border-slate-600 text-[11px] text-slate-200 placeholder-slate-500"
              />
              <span className="text-slate-500 text-[11px]">-</span>
              <input
                type="number"
                placeholder="Max"
                value={temperatureMax}
                onChange={(e) => setTemperatureMax(e.target.value)}
                className="w-16 px-1.5 py-0.5 rounded bg-slate-700 border border-slate-600 text-[11px] text-slate-200 placeholder-slate-500"
              />
              <select
                value={additiveTypeFilter}
                onChange={(e) => { setAdditiveTypeFilter(e.target.value); setSelectedExperiments([]) }}
                className="px-1.5 py-0.5 rounded bg-slate-700 border border-slate-600 text-[11px] text-slate-200"
              >
                <option value="">All Additives</option>
                {(filterOptions?.additive_types || []).map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center pt-1">
              <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded bg-slate-700 border-slate-500 border-2 cursor-pointer accent-blue-500"
                  checked={visibleExperiments.length > 0 && selectedExperiments.length === visibleExperiments.length}
                  onChange={(e) => handleSelectAll(e.target.checked)}
                />
                Select All
              </label>
            </div>
          </div>

          {/* Experiment List */}
          <div className="flex-1 overflow-y-auto">
            {visibleExperiments.length === 0 ? (
              <div className="p-4 text-center text-slate-400">
                {loading ? 'Loading...' : statusFilter ? `No ${statusFilter} experiments found` : 'No experiments found. Use Scan Database to import.'}
              </div>
            ) : (
              <div className="divide-y divide-slate-700/50">
                {visibleExperiments.map((exp, index) => (
                  <div
                    key={exp.exp_id}
                    onClick={() => setSelectedExpId(exp.exp_id)}
                    className={clsx(
                      'p-3 cursor-pointer hover:bg-slate-700/30 transition-colors',
                      selectedExpId === exp.exp_id && 'bg-slate-700/50 border-l-2 border-blue-500',
                      selectedSet.has(exp.exp_id) && 'bg-blue-500/10'
                    )}
                  >
                    <div className="flex items-start gap-2">
                      {/* Checkbox */}
                      <input
                        type="checkbox"
                        checked={selectedSet.has(exp.exp_id)}
                        onChange={(e) => toggleSelectExperiment(exp.exp_id, e)}
                        onClick={(e) => e.stopPropagation()}
                        className="w-4 h-4 rounded bg-slate-700 border-slate-500 border-2 cursor-pointer accent-blue-500 mt-0.5 flex-shrink-0"
                      />
                      <span className="text-[10px] text-slate-500 font-mono w-5 text-right flex-shrink-0 mt-0.5">{index + 1}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-xs text-white truncate">{exp.exp_id}</span>
                          <StatusBadge status={exp.status} size="sm" className="text-[10px] py-0 px-1" />
                        </div>
                        {exp.status === 'building' && (
                          <div className="mt-0.5 flex items-center gap-1 text-[9px] text-amber-300/80">
                            <div className="w-3 h-3 border-2 border-amber-400/30 border-t-amber-400 rounded-full animate-spin" />
                            <span>Generating GAFF2 artifact...</span>
                          </div>
                        )}
                        <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-300 flex-wrap">
                          <span>{exp.binder_code || exp.binder_type || '-'}</span>
                          <span>{exp.structure_size || '-'}</span>
                          <span>{exp.aging_code || exp.aging_state || '-'}</span>
                          <span>{exp.additive_label || 'None'}</span>
                        </div>
                        <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-500 flex-wrap">
                          {exp.box_lx != null && exp.box_ly != null && exp.box_lz != null && (
                            <span className="text-slate-400 font-mono">
                              {Number(exp.box_lx).toFixed(1)}x{Number(exp.box_ly).toFixed(1)}x{Number(exp.box_lz).toFixed(1)} Å
                            </span>
                          )}
                          {exp.started_at && (
                            <span title="Start time">
                              {new Date(exp.started_at).toLocaleString('ko-KR', {
                                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
                              })}
                            </span>
                          )}
                          {exp.completed_at && (
                            <span title="Completion time">
                              ~{new Date(exp.completed_at).toLocaleString('ko-KR', {
                                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
                              })}
                            </span>
                          )}
                          {exp.wall_time_seconds != null && (
                            <span className="text-slate-400">
                              ({exp.wall_time_seconds >= 3600
                                ? `${(exp.wall_time_seconds / 3600).toFixed(1)}h`
                                : exp.wall_time_seconds >= 60
                                  ? `${(exp.wall_time_seconds / 60).toFixed(0)}m`
                                  : `${exp.wall_time_seconds.toFixed(0)}s`})
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setDeleteModal({ open: true, expId: exp.exp_id })
                          }}
                          className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                        <ChevronRight className="w-4 h-4 text-slate-500" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Count */}
          <div className="p-2 border-t border-slate-700 text-xs text-slate-400 text-center">
            {selectedExperiments.length > 0
              ? `${selectedExperiments.length} selected / ${visibleExperiments.length}`
              : `${visibleExperiments.length} experiments`}
          </div>
        </div>

        {/* Right Panel - Experiment Detail (65%) */}
        <div className="w-[65%] card">
          <ExperimentDetail expId={selectedExpId} />
        </div>
      </div>

      {/* Fixed bottom selection action bar */}
      {selectedExperiments.length > 0 && (
        <div className="fixed bottom-0 left-72 right-0 z-40 flex items-center gap-3 px-4 py-2.5 bg-slate-800 border-t border-slate-700">
          <span className="text-xs text-slate-300">{selectedExperiments.length} selected</span>
          <button
            onClick={handleBulkDelete}
            className="px-3 py-1 rounded text-xs font-medium bg-red-600 hover:bg-red-700 text-white flex items-center gap-1"
          >
            <Trash2 className="w-3 h-3" />
            Delete Selected
          </button>
          <button
            onClick={() => setSelectedExperiments([])}
            className="px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-200"
          >
            Clear
          </button>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <DeleteModal
        isOpen={deleteModal.open}
        expId={deleteModal.expId}
        onClose={() => setDeleteModal({ open: false, expId: null })}
        onConfirm={handleDelete}
      />
    </div>
  )
}

export default BinderCellsPage
