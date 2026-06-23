import { useState, useMemo } from 'react'
import clsx from 'clsx'
import { RefreshCw, Download, Upload, HardDrive, X } from 'lucide-react'
import { useScanAssets, useImportAssets, useBackupToNas, useLoadFromNas, useApplyNasLoad, useNasStatus } from '../hooks/useApiDataSync'

const ASSET_TYPE_LABELS = {
  interface_molecule_cells: 'Interface Molecule Cells',
  crystal_structures: 'Crystal Structures',
  all: 'All Assets',
}

function DataSyncModal({ open, onClose, assetType = 'all' }) {
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(() => new Set())
  const [actionResult, setActionResult] = useState(null)
  const [nasPreview, setNasPreview] = useState(null)
  const [storedManifestPath, setStoredManifestPath] = useState(null)

  const scanMutation = useScanAssets()
  const importMutation = useImportAssets()
  const backupMutation = useBackupToNas()
  const loadMutation = useLoadFromNas()
  const applyMutation = useApplyNasLoad()
  const { data: nasStatus } = useNasStatus()

  const nasConfigured = nasStatus?.configured ?? false

  const assets = useMemo(() => data?.assets || [], [data])
  const newAssets = useMemo(() => assets.filter((a) => !a.already_synced), [assets])

  const handleScan = () => {
    setData(null)
    setSelected(new Set())
    setActionResult(null)
    scanMutation.mutate(assetType, {
      onSuccess: (result) => setData(result),
    })
  }

  const handleSelectAll = () => {
    if (selected.size === newAssets.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(newAssets.map((a) => a.asset_id)))
    }
  }

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleImport = () => {
    if (selected.size === 0) return
    importMutation.mutate(
      { asset_type: assetType, asset_ids: [...selected] },
      {
        onSuccess: (result) => {
          setActionResult(result)
          setSelected(new Set())
          // Re-scan after import
          scanMutation.mutate(assetType, { onSuccess: (r) => setData(r) })
        },
      },
    )
  }

  const handleBackup = () => {
    backupMutation.mutate([assetType === 'all' ? 'all' : assetType], {
      onSuccess: (result) => {
        setActionResult({ type: 'backup', ...result })
      },
    })
  }

  const handleLoadPreview = () => {
    setNasPreview(null)
    setStoredManifestPath(null)
    loadMutation.mutate(null, {
      onSuccess: (result) => {
        setNasPreview(result)
        setStoredManifestPath(result.manifest_path || null)
        setActionResult({ type: 'load', ...result })
      },
    })
  }

  const handleApplyRestore = () => {
    applyMutation.mutate({ manifest_path: storedManifestPath }, {
      onSuccess: (result) => {
        setNasPreview(null)
        setStoredManifestPath(null)
        setActionResult({ type: 'apply', ...result })
      },
    })
  }

  const handleClose = () => {
    setData(null)
    setSelected(new Set())
    setActionResult(null)
    setNasPreview(null)
    setStoredManifestPath(null)
    onClose()
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-[780px] max-h-[85vh] flex flex-col border border-slate-700">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Data Sync — {ASSET_TYPE_LABELS[assetType] || assetType}
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Scan filesystem for data assets and import into the system
            </p>
          </div>
          <button onClick={handleClose} className="text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Actions bar */}
        <div className="px-6 py-3 border-b border-slate-700 flex items-center gap-3">
          <button
            onClick={handleScan}
            disabled={scanMutation.isPending}
            className="btn btn-primary flex items-center gap-2"
          >
            <RefreshCw className={clsx('w-4 h-4', scanMutation.isPending && 'animate-spin')} />
            {scanMutation.isPending ? 'Scanning...' : 'Scan'}
          </button>
          {data && selected.size > 0 && (
            <button
              onClick={handleImport}
              disabled={importMutation.isPending}
              className="btn btn-primary flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Import {selected.size} Selected
            </button>
          )}
          <div className="flex-1" />
          {/* NAS buttons */}
          <button
            onClick={handleBackup}
            disabled={!nasConfigured || backupMutation.isPending}
            className="btn btn-outline flex items-center gap-2 disabled:opacity-30"
            title={!nasConfigured ? 'DATA_SYNC_NAS_ROOT not configured' : 'Full workspace backup to NAS'}
          >
            <Upload className="w-4 h-4" />
            Full Backup
          </button>
          <button
            onClick={handleLoadPreview}
            disabled={!nasConfigured || loadMutation.isPending}
            className="btn btn-outline flex items-center gap-2 disabled:opacity-30"
            title={!nasConfigured ? 'DATA_SYNC_NAS_ROOT not configured' : 'Preview NAS backup'}
          >
            <HardDrive className="w-4 h-4" />
            Load Preview
          </button>
          {nasPreview?.success && storedManifestPath && (
            <button
              onClick={handleApplyRestore}
              disabled={applyMutation.isPending}
              className="btn btn-primary flex items-center gap-2 text-amber-300 border-amber-500/30"
              title="Apply restore from NAS backup (creates local snapshot first)"
            >
              {applyMutation.isPending ? 'Restoring...' : `Apply (${nasPreview.items_found} items)`}
            </button>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {/* Action result */}
          {actionResult && (
            <div className={clsx(
              'p-3 rounded-lg text-sm',
              ['backup', 'load', 'apply'].includes(actionResult.type)
                ? (actionResult.success
                  ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                  : 'bg-red-500/10 text-red-300 border border-red-500/20')
                : (actionResult.failed > 0
                  ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20'
                  : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20')
            )}>
              {['backup', 'load', 'apply'].includes(actionResult.type)
                ? actionResult.message
                : `Imported ${actionResult.imported} asset(s)${actionResult.failed > 0 ? `, ${actionResult.failed} failed` : ''}.`
              }
            </div>
          )}

          {/* Summary cards */}
          {data && (
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Discovered', value: data.total_discovered, color: 'text-white' },
                { label: 'New', value: data.new_items, color: 'text-emerald-400' },
                { label: 'Already Synced', value: data.already_synced, color: 'text-blue-400' },
              ].map((card) => (
                <div key={card.label} className="bg-slate-700/40 rounded-lg px-4 py-3 text-center">
                  <div className={clsx('text-2xl font-bold', card.color)}>{card.value}</div>
                  <div className="text-xs text-slate-400 mt-0.5">{card.label}</div>
                </div>
              ))}
            </div>
          )}

          {/* Asset table */}
          {data && assets.length > 0 && (
            <div className="border border-slate-700 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-700/50 text-left text-xs text-slate-400">
                    <th className="px-3 py-2 w-8">
                      <input
                        type="checkbox"
                        checked={selected.size > 0 && selected.size === newAssets.length}
                        onChange={handleSelectAll}
                        disabled={newAssets.length === 0}
                        className="w-3.5 h-3.5 rounded bg-slate-700 border-slate-500 accent-blue-500"
                      />
                    </th>
                    <th className="px-3 py-2">Asset ID</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Synced</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/50">
                  {assets.map((asset) => {
                    const isNew = !asset.already_synced
                    const isSelected = selected.has(asset.asset_id)
                    return (
                      <tr
                        key={asset.asset_id}
                        className={clsx(
                          'hover:bg-slate-700/30 transition-colors',
                          asset.already_synced && 'opacity-50',
                        )}
                      >
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(asset.asset_id)}
                            disabled={!isNew}
                            className="w-3.5 h-3.5 rounded bg-slate-700 border-slate-500 accent-blue-500 disabled:opacity-30"
                          />
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-white truncate max-w-[250px]" title={asset.asset_id}>
                          {asset.asset_id}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-400">
                          {asset.asset_type === 'interface_molecule_cells' ? 'Interface' : 'Crystal'}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {asset.status === 'ready' ? (
                            <span className="text-emerald-400">Ready</span>
                          ) : (
                            <span className="text-amber-400">{asset.status}</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {asset.already_synced ? (
                            <span className="text-blue-400">Yes</span>
                          ) : (
                            <span className="text-slate-500">No</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Empty states */}
          {data && assets.length === 0 && (
            <div className="text-center py-8 text-slate-500">
              <p className="text-sm">No assets found on filesystem.</p>
              <p className="text-xs mt-1">Copy data directories from another machine first.</p>
            </div>
          )}

          {!data && !scanMutation.isPending && (
            <div className="text-center py-8 text-slate-500">
              <p className="text-sm">Click Scan to discover data assets on the filesystem.</p>
            </div>
          )}

          {scanMutation.isPending && (
            <div className="text-center py-8">
              <RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto" />
              <p className="text-sm text-slate-400 mt-2">Scanning...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default DataSyncModal
