import { useState, useMemo, useEffect } from 'react'
import { X, Search, Download, RefreshCw, AlertTriangle, CheckCircle2, Clock, HelpCircle, FolderOpen, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import { useScanDatabase, useImportExperiments, useDeleteScannedExperiments } from '../hooks/useApi'

const COMPAT_CONFIG = {
  compatible:            { label: 'Compatible',  color: 'bg-emerald-500/15 text-emerald-400', icon: CheckCircle2 },
  compatible_incomplete: { label: 'Incomplete',  color: 'bg-blue-500/15 text-blue-400',      icon: Clock },
  protocol_mismatch:    { label: 'Mismatch',    color: 'bg-amber-500/15 text-amber-400',     icon: AlertTriangle },
  hash_unverifiable:    { label: 'Unverifiable', color: 'bg-slate-500/15 text-slate-400',     icon: HelpCircle },
  no_metadata:          { label: 'No Metadata',  color: 'bg-slate-500/15 text-slate-400',     icon: HelpCircle },
  empty:                { label: 'Empty',         color: 'bg-slate-500/15 text-slate-400',     icon: FolderOpen },
}

// Deletable = incompatible experiments (not already in DB)
const DELETABLE_COMPAT = new Set(['protocol_mismatch', 'hash_unverifiable', 'no_metadata', 'empty'])

function CompatBadge({ compatibility }) {
  const cfg = COMPAT_CONFIG[compatibility] || COMPAT_CONFIG.empty
  const Icon = cfg.icon
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium', cfg.color)}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  )
}

export default function ScanDatabaseModal({ open, onClose }) {
  const scanMutation = useScanDatabase()
  const importMutation = useImportExperiments()
  const deleteMutation = useDeleteScannedExperiments()
  const [selected, setSelected] = useState(new Set())
  const [forceImport, setForceImport] = useState(false)
  const [actionResult, setActionResult] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const data = scanMutation.data
  const experiments = useMemo(() => data?.experiments || [], [data])

  // Importable set
  const importable = useMemo(() => {
    const allowed = forceImport
      ? new Set(['compatible', 'compatible_incomplete', 'protocol_mismatch'])
      : new Set(['compatible', 'compatible_incomplete'])
    return new Set(
      experiments
        .filter((e) => allowed.has(e.compatibility) && !e.already_in_db)
        .map((e) => e.exp_id)
    )
  }, [experiments, forceImport])

  // Deletable set (incompatible dirs not in DB)
  const deletable = useMemo(() => {
    return new Set(
      experiments
        .filter((e) => DELETABLE_COMPAT.has(e.compatibility) && !e.already_in_db)
        .map((e) => e.exp_id)
    )
  }, [experiments])

  // All selectable = importable + deletable
  const selectable = useMemo(() => {
    return new Set([...importable, ...deletable])
  }, [importable, deletable])

  // Prune selected when selectable changes
  useEffect(() => {
    setSelected((prev) => {
      const pruned = new Set([...prev].filter((id) => selectable.has(id)))
      return pruned.size === prev.size ? prev : pruned
    })
  }, [selectable])

  // Partition selected into importable / deletable counts
  const selectedImportableCount = useMemo(
    () => [...selected].filter((id) => importable.has(id)).length,
    [selected, importable]
  )
  const selectedDeletableCount = useMemo(
    () => [...selected].filter((id) => deletable.has(id)).length,
    [selected, deletable]
  )

  // Auto-dismiss delete confirmation when no deletable items are selected
  useEffect(() => {
    if (selectedDeletableCount === 0) {
      setDeleteConfirm(false)
    }
  }, [selectedDeletableCount])

  const handleScan = () => {
    setSelected(new Set())
    setActionResult(null)
    setDeleteConfirm(false)
    scanMutation.mutate()
  }

  const toggleSelect = (expId) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(expId)) next.delete(expId)
      else next.add(expId)
      return next
    })
  }

  const handleSelectAll = () => {
    if (selected.size === selectable.size) {
      setSelected(new Set())
    } else {
      setSelected(new Set(selectable))
    }
  }

  const selectAllImportable = () => setSelected(new Set(importable))
  const selectAllDeletable = () => setSelected(new Set(deletable))

  const handleImport = () => {
    const ids = [...selected].filter((id) => importable.has(id))
    if (ids.length === 0) return
    importMutation.mutate(
      { exp_ids: ids, force_import: forceImport },
      {
        onSuccess: (result) => {
          setActionResult({ type: 'import', ...result })
          setSelected(new Set())
          scanMutation.mutate()
        },
      }
    )
  }

  const handleDelete = () => {
    const ids = [...selected].filter((id) => deletable.has(id))
    if (ids.length === 0) return
    deleteMutation.mutate(
      { exp_ids: ids },
      {
        onSuccess: (result) => {
          setActionResult({ type: 'delete', ...result })
          setSelected(new Set())
          setDeleteConfirm(false)
          scanMutation.mutate()
        },
      }
    )
  }

  if (!open) return null

  const isBusy = scanMutation.isPending || importMutation.isPending || deleteMutation.isPending

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-[90vw] max-w-5xl max-h-[85vh] flex flex-col border border-slate-700">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div>
            <h2 className="text-lg font-semibold text-white">Scan Database</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Discover filesystem experiments — import compatible ones or clean up incompatible directories.
            </p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Action bar */}
          <div className="flex items-center gap-3 flex-wrap">
            <button
              onClick={handleScan}
              disabled={isBusy}
              className="btn btn-primary flex items-center gap-2"
            >
              {scanMutation.isPending ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Search className="w-4 h-4" />
              )}
              {data ? 'Re-scan' : 'Scan Filesystem'}
            </button>

            {data && (
              <>
                {/* Import button */}
                <button
                  onClick={handleImport}
                  disabled={selectedImportableCount === 0 || isBusy}
                  className="btn btn-secondary flex items-center gap-2"
                >
                  {importMutation.isPending ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  Import ({selectedImportableCount})
                </button>

                {/* Delete button */}
                <button
                  onClick={() => selectedDeletableCount > 0 && setDeleteConfirm(true)}
                  disabled={selectedDeletableCount === 0 || isBusy}
                  className="btn flex items-center gap-2 bg-red-600/80 hover:bg-red-600 text-white disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {deleteMutation.isPending ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                  Delete ({selectedDeletableCount})
                </button>

                {/* Quick-select helpers */}
                <div className="ml-auto flex items-center gap-3">
                  {importable.size > 0 && (
                    <button
                      onClick={selectAllImportable}
                      className="text-[10px] text-emerald-400 hover:text-emerald-300 underline underline-offset-2"
                    >
                      Select all importable ({importable.size})
                    </button>
                  )}
                  {deletable.size > 0 && (
                    <button
                      onClick={selectAllDeletable}
                      className="text-[10px] text-red-400 hover:text-red-300 underline underline-offset-2"
                    >
                      Select all deletable ({deletable.size})
                    </button>
                  )}
                  <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={forceImport}
                      onChange={(e) => setForceImport(e.target.checked)}
                      className="w-3.5 h-3.5 rounded bg-slate-700 border-slate-500 accent-amber-500"
                    />
                    Force import (mismatch)
                  </label>
                </div>
              </>
            )}
          </div>

          {/* Delete confirmation */}
          {deleteConfirm && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3 flex items-center justify-between">
              <div className="text-sm text-red-300">
                <Trash2 className="w-4 h-4 inline mr-1.5 -mt-0.5" />
                Permanently delete {selectedDeletableCount} directories. This action cannot be undone.
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setDeleteConfirm(false)}
                  className="btn btn-secondary text-xs px-3 py-1"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={selectedDeletableCount === 0 || deleteMutation.isPending}
                  className="btn bg-red-600 hover:bg-red-700 text-white text-xs px-3 py-1 flex items-center gap-1"
                >
                  {deleteMutation.isPending && <RefreshCw className="w-3 h-3 animate-spin" />}
                  Confirm Delete
                </button>
              </div>
            </div>
          )}

          {/* Action result banner */}
          {actionResult && (
            <div className={clsx(
              'rounded-lg px-4 py-2.5 text-sm',
              actionResult.type === 'delete'
                ? (actionResult.failed > 0
                  ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20'
                  : 'bg-red-500/10 text-red-300 border border-red-500/20')
                : (actionResult.failed > 0
                  ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20'
                  : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20')
            )}>
              {actionResult.type === 'delete' ? (
                <>Deleted {actionResult.deleted} directory(s){actionResult.failed > 0 && `, ${actionResult.failed} failed`}.</>
              ) : (
                <>Imported {actionResult.imported} experiment(s){actionResult.failed > 0 && `, ${actionResult.failed} failed`}.</>
              )}
            </div>
          )}

          {/* Summary cards */}
          {data && (
            <div className="grid grid-cols-4 gap-3">
              {[
                { label: 'Discovered', value: data.total_discovered, color: 'text-white' },
                { label: 'Compatible', value: data.compatible, color: 'text-emerald-400' },
                { label: 'Incompatible', value: data.incompatible, color: 'text-amber-400' },
                { label: 'Already Imported', value: data.already_imported, color: 'text-blue-400' },
              ].map((card) => (
                <div key={card.label} className="bg-slate-700/40 rounded-lg px-4 py-3 text-center">
                  <div className={clsx('text-2xl font-bold', card.color)}>{card.value}</div>
                  <div className="text-xs text-slate-400 mt-0.5">{card.label}</div>
                </div>
              ))}
            </div>
          )}

          {/* Experiment table */}
          {data && experiments.length > 0 && (
            <div className="border border-slate-700 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-700/50 text-left text-xs text-slate-400">
                    <th className="px-3 py-2 w-8">
                      <input
                        type="checkbox"
                        checked={selected.size > 0 && selected.size === selectable.size}
                        onChange={handleSelectAll}
                        disabled={selectable.size === 0}
                        className="w-3.5 h-3.5 rounded bg-slate-700 border-slate-500 accent-blue-500"
                      />
                    </th>
                    <th className="px-3 py-2">Experiment ID</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Temp</th>
                    <th className="px-3 py-2">Atoms</th>
                    <th className="px-3 py-2">Protocol Hash</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Compatibility</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/50">
                  {experiments.map((exp) => {
                    const canSelect = selectable.has(exp.exp_id)
                    const isSelected = selected.has(exp.exp_id)
                    const isDeletableItem = deletable.has(exp.exp_id)
                    return (
                      <tr
                        key={exp.exp_id}
                        className={clsx(
                          'hover:bg-slate-700/30 transition-colors',
                          exp.already_in_db && 'opacity-50',
                          isSelected && isDeletableItem && 'bg-red-500/5',
                        )}
                      >
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(exp.exp_id)}
                            disabled={!canSelect}
                            className={clsx(
                              'w-3.5 h-3.5 rounded bg-slate-700 border-slate-500 disabled:opacity-30',
                              isDeletableItem ? 'accent-red-500' : 'accent-blue-500',
                            )}
                          />
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-white truncate max-w-[200px]" title={exp.exp_id}>
                          {exp.exp_id}
                          {exp.already_in_db && (
                            <span className="ml-1.5 text-[9px] bg-blue-500/15 text-blue-400 rounded px-1 py-px">
                              DB
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {exp.study_type === 'single_molecule_vacuum' ? (
                            <span className="text-purple-400">SM</span>
                          ) : exp.study_type === 'layer_bulkff' ? (
                            <span className="text-cyan-400">Layer</span>
                          ) : (
                            <span className="text-slate-400">{exp.study_type || 'bulk'}</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-slate-300">
                          {exp.temperature_k ? `${exp.temperature_k} K` : '-'}
                        </td>
                        <td className="px-3 py-2 text-slate-300">
                          {exp.total_atoms ? Number(exp.total_atoms).toLocaleString() : '-'}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-slate-400">
                          {exp.protocol_hash_found || '-'}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {exp.lammps_completed ? (
                            <span className="text-emerald-400">Completed</span>
                          ) : exp.has_log_lammps ? (
                            <span className="text-amber-400">Incomplete</span>
                          ) : exp.has_in_lammps ? (
                            <span className="text-slate-400">Built</span>
                          ) : (
                            <span className="text-slate-500">Empty</span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <CompatBadge compatibility={exp.compatibility} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Empty state */}
          {!data && !scanMutation.isPending && (
            <div className="text-center py-16 text-slate-400">
              <Search className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p>Click &quot;Scan Filesystem&quot; to discover experiments.</p>
            </div>
          )}

          {scanMutation.isError && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-300">
              Scan failed: {scanMutation.error?.message || 'Unknown error'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
