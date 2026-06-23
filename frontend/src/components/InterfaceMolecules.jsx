import { useMemo, useState } from 'react'
import { Trash2 } from 'lucide-react'
import {
  useInterfaceMolecules,
  useInterfaceMoleculeCells,
  useInterfaceMoleculeCellPreview,
  useDeleteInterfaceMoleculeCell,
  useBatchGenerateInterfaceMoleculeCells,
} from '../hooks/useApiInterfaceMolecules'
import { NotificationBanner } from './shared/index'
import { useNotification } from '../hooks/useNotification'
import PageHeader from './shared/PageHeader'
import { HEADER_ACTION_BUTTON } from './shared/headerActionStyles'
import { ROUTE_KEYS } from '../navigation/routeMeta'

import { RefreshCw } from 'lucide-react'
import DataSyncModal from './DataSyncModal'
import InterfaceMoleculeCreatePanel from './interface-molecules/InterfaceMoleculeCreatePanel'
import InterfaceMoleculeLibraryPanel from './interface-molecules/InterfaceMoleculeLibraryPanel'
import InterfaceMoleculeDetailPanel from './interface-molecules/InterfaceMoleculeDetailPanel'
import { extractElementsFromXyz } from './molecule-viewer'

function InterfaceMoleculesPage({ mode = 'all' }) {
  const showCreatePanel = mode === 'all' || mode === 'create'
  const showLibraryPanel = mode === 'all' || mode === 'library'
  const [selectedMolId, setSelectedMolId] = useState(null)
  const [selectedCellId, setSelectedCellId] = useState(null)
  const [selectedCells, setSelectedCells] = useState([])
  const [representation, setRepresentation] = useState('ball_and_stick')
  const [batchResult, setBatchResult] = useState(null)
  const [dataSyncOpen, setDataSyncOpen] = useState(false)
  const pageRouteKey =
    showCreatePanel && !showLibraryPanel
      ? ROUTE_KEYS.SINGLE_JOB_INTERFACE_MOLECULES
      : ROUTE_KEYS.INTERFACE_MOLECULES_DATABASE

  // Molecule catalog
  const { data: moleculesData, loading: moleculesLoading } = useInterfaceMolecules()

  // Cell library
  const { data: cellsData, loading: cellsLoading, execute: refreshCells } = useInterfaceMoleculeCells({
    visibility: 'library',
    limit: 200,
  })

  // Cell preview
  const {
    data: cellPreview,
    loading: cellPreviewLoading,
    error: cellPreviewError,
    execute: refreshCellPreview,
  } = useInterfaceMoleculeCellPreview(selectedCellId, Boolean(selectedCellId))

  const deleteMutation = useDeleteInterfaceMoleculeCell()
  const batchGenerateMutation = useBatchGenerateInterfaceMoleculeCells()
  const { notification, notify, dismiss } = useNotification()

  const molecules = useMemo(() => moleculesData?.items || [], [moleculesData])
  const cells = useMemo(() => cellsData?.items || [], [cellsData])

  const selectedCell = useMemo(
    () => cells.find((c) => c.cell_id === selectedCellId) || null,
    [cells, selectedCellId]
  )

  const cellPreviewElements = useMemo(
    () => extractElementsFromXyz(cellPreview?.xyz),
    [cellPreview?.xyz]
  )

  const selectedCellSet = new Set(selectedCells)

  const toggleSelectCell = (cellId, e) => {
    e.stopPropagation()
    setSelectedCells((prev) =>
      prev.includes(cellId) ? prev.filter((id) => id !== cellId) : [...prev, cellId]
    )
  }

  const handleSelectAllCells = (checked) => {
    setSelectedCells(checked ? cells.map((c) => c.cell_id) : [])
  }

  const handleBulkDeleteCells = async () => {
    if (selectedCells.length === 0) return
    if (!confirm(`Delete ${selectedCells.length} selected interface cells?`)) return
    let failed = 0
    for (const id of selectedCells) {
      try {
        await deleteMutation.mutateAsync(id)
      } catch {
        failed += 1
      }
    }
    if (selectedCellId && selectedCells.includes(selectedCellId)) {
      setSelectedCellId(null)
    }
    setSelectedCells([])
    refreshCells()
    notify(
      failed > 0 ? 'error' : 'success',
      failed > 0
        ? `${selectedCells.length - failed} deleted, ${failed} failed`
        : `${selectedCells.length} deleted`
    )
  }

  const handleBatchGenerate = async (params) => {
    try {
      const result = await batchGenerateMutation.mutateAsync(params)
      setBatchResult(result)
      // Auto-select first generated cell
      if (result.cells?.length > 0) {
        setSelectedCellId(result.cells[0].cell_id)
      }
      refreshCells()
      const level = result.failed_count > 0
        ? (result.generated_count > 0 ? 'warning' : 'error')
        : 'success'
      notify(
        level,
        `Generated ${result.generated_count}, Skipped ${result.skipped_count}, Failed ${result.failed_count}`
      )
    } catch (err) {
      notify('error', err?.response?.data?.detail || err?.message || 'Batch generation failed')
    }
  }

  // Clear batch result when molecule selection changes
  const handleMolIdChange = (molId) => {
    setSelectedMolId(molId)
    setBatchResult(null)
  }

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col">
      {/* Fixed top area */}
      <div className="flex-shrink-0 space-y-4">
        <PageHeader routeKey={pageRouteKey}>
          <button
            onClick={() => setDataSyncOpen(true)}
            className={HEADER_ACTION_BUTTON}
          >
            <RefreshCw className="w-4 h-4" />
            Data Sync
          </button>
        </PageHeader>
        <NotificationBanner notification={notification} onDismiss={dismiss} />
        <DataSyncModal
          open={dataSyncOpen}
          onClose={() => setDataSyncOpen(false)}
          assetType="interface_molecule_cells"
        />

        {showCreatePanel && (
          <InterfaceMoleculeCreatePanel
            molecules={molecules}
            loading={moleculesLoading}
            selectedMolId={selectedMolId}
            setSelectedMolId={handleMolIdChange}
            // Batch generation
            batchGenerateMutation={batchGenerateMutation}
            handleBatchGenerate={handleBatchGenerate}
            batchResult={batchResult}
            setBatchResult={setBatchResult}
            // Cell preview (reuse existing)
            selectedCellId={selectedCellId}
            setSelectedCellId={setSelectedCellId}
            cellPreview={cellPreview}
            cellPreviewLoading={cellPreviewLoading}
          />
        )}
      </div>

      {/* Scrollable content area */}
      {showLibraryPanel && (
        <div className="flex-1 overflow-auto min-h-0 mt-4">
          <div className="grid gap-4 md:grid-cols-[6fr_4fr]">
            <InterfaceMoleculeLibraryPanel
              cells={cells}
              loading={cellsLoading}
              execute={refreshCells}
              selectedCellId={selectedCellId}
              setSelectedCellId={setSelectedCellId}
              selectedCells={selectedCells}
              selectedCellSet={selectedCellSet}
              toggleSelectCell={toggleSelectCell}
              handleSelectAllCells={handleSelectAllCells}
            />

            <InterfaceMoleculeDetailPanel
              selectedCellId={selectedCellId}
              selectedCell={selectedCell}
              preview={cellPreview}
              previewLoading={cellPreviewLoading}
              previewError={cellPreviewError}
              previewElements={cellPreviewElements}
              representation={representation}
              setRepresentation={setRepresentation}
              refreshPreview={refreshCellPreview}
            />
          </div>
        </div>
      )}

      {/* Fixed bottom selection action bar */}
      {selectedCells.length > 0 && (
        <div className="fixed bottom-0 left-72 right-0 z-40 flex items-center gap-3 px-4 py-2.5 bg-slate-800 border-t border-slate-700">
          <span className="text-xs text-slate-300">{selectedCells.length} selected</span>
          <button
            onClick={handleBulkDeleteCells}
            className="px-3 py-1 rounded text-xs font-medium bg-red-600 hover:bg-red-700 text-white flex items-center gap-1"
          >
            <Trash2 className="w-3 h-3" />
            Delete Selected
          </button>
          <button
            onClick={() => setSelectedCells([])}
            className="px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-200"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}

export default InterfaceMoleculesPage
