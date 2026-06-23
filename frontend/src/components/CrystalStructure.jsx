import { useEffect, useMemo, useState } from 'react'
import { Trash2, RefreshCw } from 'lucide-react'
import DataSyncModal from './DataSyncModal'
import {
  useBatchGenerateCrystalSizes,
  useCrystalStructurePreview,
  useCrystalStructures,
  useDeleteCrystalStructure,
} from '../hooks/useApiCrystalStructures'
import {
  buildMaterialUnitPreview,
  DEFAULT_THICKNESS_ANGSTROM,
  formatCellMetrics,
  UNIT_PREVIEW_ELEMENTS_BY_MATERIAL,
} from './crystal-structures/utils'
import { extractElementsFromXyz } from './molecule-viewer'
import { NotificationBanner } from './shared/index'
import { useNotification } from '../hooks/useNotification'
import PageHeader from './shared/PageHeader'
import { HEADER_ACTION_BUTTON } from './shared/headerActionStyles'
import { ROUTE_KEYS } from '../navigation/routeMeta'

import CrystalCreatePanel from './crystal-structures/CrystalCreatePanel'
import CrystalLibraryPanel from './crystal-structures/CrystalLibraryPanel'
import CrystalDetailPanel from './crystal-structures/CrystalDetailPanel'

// ohMin/ohMax: experimental/theoretical hydroxyl density range (OH/nm²)
// Pure metals have no oxide surface → oh = 0
const CRYSTAL_SYSTEM_INFO = {
  SiO2:  { system: 'Hexagonal', spaceGroup: 'P3₂21',  structure: 'α-Quartz',  a: 4.913, b: 4.913, c: 5.405,  gamma: 120, nAtoms: 9,  surface: '001', ohMin: 4.2, ohMax: 4.9 },
  CaCO3: { system: 'Trigonal',  spaceGroup: 'R-3c',    structure: 'Calcite',   a: 4.990, b: 4.990, c: 17.062, gamma: 120, nAtoms: 30, surface: '001', ohMin: 2.0, ohMax: 5.0 },
  Al2O3: { system: 'Trigonal',  spaceGroup: 'R-3c',    structure: 'Corundum',  a: 4.759, b: 4.759, c: 12.991, gamma: 120, nAtoms: 30, surface: '001', ohMin: 8.0, ohMax: 12.0 },
  MgO:   { system: 'Cubic',     spaceGroup: 'Fm-3m',   structure: 'Rocksalt',  a: 4.213, b: 4.213, c: 4.213,  gamma: 90,  nAtoms: 8,  surface: '001', ohMin: 6.0, ohMax: 8.0 },
  Fe2O3: { system: 'Trigonal',  spaceGroup: 'R-3c',    structure: 'Hematite',  a: 5.035, b: 5.035, c: 13.750, gamma: 120, nAtoms: 30, surface: '001', ohMin: 5.0, ohMax: 10.0 },
  MgCO3: { system: 'Trigonal',  spaceGroup: 'R-3c',    structure: 'Magnesite', a: 4.633, b: 4.633, c: 15.020, gamma: 120, nAtoms: 30, surface: '001', ohMin: 2.0, ohMax: 5.0 },
  CaO:   { system: 'Cubic',     spaceGroup: 'Fm-3m',   structure: 'Rocksalt',  a: 4.810, b: 4.810, c: 4.810,  gamma: 90,  nAtoms: 8,  surface: '001', ohMin: 6.0, ohMax: 8.0 },
  TiO2:  { system: 'Tetragonal',spaceGroup: 'P4₂/mnm', structure: 'Rutile',    a: 4.594, b: 4.594, c: 2.958,  gamma: 90,  nAtoms: 6,  surface: '110', ohMin: 5.0, ohMax: 7.0 },
  ZnO:   { system: 'Hexagonal', spaceGroup: 'P6₃mc',   structure: 'Wurtzite',  a: 3.250, b: 3.250, c: 5.207,  gamma: 120, nAtoms: 4,  surface: '001', ohMin: 4.0, ohMax: 7.0 },
  NaCl:  { system: 'Cubic',     spaceGroup: 'Fm-3m',   structure: 'Rocksalt',  a: 5.640, b: 5.640, c: 5.640,  gamma: 90,  nAtoms: 8,  surface: '001', ohMin: 0,   ohMax: 0 },
  KCl:   { system: 'Cubic',     spaceGroup: 'Fm-3m',   structure: 'Rocksalt',  a: 6.292, b: 6.292, c: 6.292,  gamma: 90,  nAtoms: 8,  surface: '001', ohMin: 0,   ohMax: 0 },
  Al:    { system: 'Cubic',     spaceGroup: 'Fm-3m',   structure: 'FCC',       a: 4.049, b: 4.049, c: 4.049,  gamma: 90,  nAtoms: 4,  surface: '111', ohMin: 0,   ohMax: 0 },
  Fe:    { system: 'Cubic',     spaceGroup: 'Im-3m',   structure: 'BCC',       a: 2.866, b: 2.866, c: 2.866,  gamma: 90,  nAtoms: 2,  surface: '110', ohMin: 0,   ohMax: 0 },
  Cu:    { system: 'Cubic',     spaceGroup: 'Fm-3m',   structure: 'FCC',       a: 3.615, b: 3.615, c: 3.615,  gamma: 90,  nAtoms: 4,  surface: '111', ohMin: 0,   ohMax: 0 },
  Ni:    { system: 'Cubic',     spaceGroup: 'Fm-3m',   structure: 'FCC',       a: 3.524, b: 3.524, c: 3.524,  gamma: 90,  nAtoms: 4,  surface: '111', ohMin: 0,   ohMax: 0 },
}

function CrystalStructuresPage({ mode = 'all' }) {
  const showCreatePanel = mode === 'all' || mode === 'create'
  const showLibraryPanel = mode === 'all' || mode === 'library'
  const [statusFilter] = useState('ready')
  const [dataSyncOpen, setDataSyncOpen] = useState(false)
  const [material, setMaterial] = useState('SiO2')
  const [thickness, setThickness] = useState(DEFAULT_THICKNESS_ANGSTROM)
  const [hydroxylated, setHydroxylated] = useState(true)
  const [hydroxylDensity, setHydroxylDensity] = useState(4.6)

  // Auto-set OH density mid-value when material changes
  useEffect(() => {
    const info = CRYSTAL_SYSTEM_INFO[material]
    if (!info) return
    if (info.ohMax <= 0) {
      setHydroxylated(false)
      setHydroxylDensity(0)
    } else {
      setHydroxylated(true)
      setHydroxylDensity(Number(((info.ohMin + info.ohMax) / 2).toFixed(1)))
    }
  }, [material])
  const [representation, setRepresentation] = useState('ball_and_stick')
  const [selectedCrystalId, setSelectedCrystalId] = useState(null)
  const [selectedCrystals, setSelectedCrystals] = useState([])
  const [batchResult, setBatchResult] = useState(null)
  const pageRouteKey =
    showCreatePanel && !showLibraryPanel
      ? ROUTE_KEYS.SINGLE_JOB_CRYSTAL_STRUCTURES
      : ROUTE_KEYS.CRYSTAL_STRUCTURES_DATABASE

  const { data, loading, error, execute } = useCrystalStructures({
    status: statusFilter || undefined,
    visibility: 'library',
    limit: 200,
  })
  const deleteMutation = useDeleteCrystalStructure()
  const batchGenerateMutation = useBatchGenerateCrystalSizes()
  const { notification, notify, dismiss } = useNotification()
  const selectedCrystalSet = new Set(selectedCrystals)

  useEffect(() => {
    if (error) notify('error', String(error))
  }, [error, notify])

  const items = useMemo(() => data?.items || [], [data])
  const selectedCrystal = useMemo(
    () => items.find((item) => item.crystal_id === selectedCrystalId) || null,
    [items, selectedCrystalId]
  )
  const {
    data: preview,
    loading: previewLoading,
    error: previewError,
    execute: refreshPreview,
  } = useCrystalStructurePreview(selectedCrystalId, Boolean(selectedCrystalId))
  const previewErrorMessage = useMemo(() => {
    if (!previewError) return ''
    if (previewError === 'Not Found') return 'Preview endpoint not found. Restart backend.'
    return previewError
  }, [previewError])
  const libraryCellMetrics = useMemo(() => formatCellMetrics(preview?.box_size), [preview])
  const previewAtomTypes = useMemo(() => extractElementsFromXyz(preview?.xyz), [preview?.xyz])

  const materialElements = useMemo(
    () => UNIT_PREVIEW_ELEMENTS_BY_MATERIAL[material] || [],
    [material]
  )
  const crystalInfo = useMemo(() => CRYSTAL_SYSTEM_INFO[material] || {}, [material])
  const unitPreview = useMemo(() => buildMaterialUnitPreview(material), [material])

  const toggleSelectCrystal = (crystalId, e) => {
    e.stopPropagation()
    setSelectedCrystals((prev) =>
      prev.includes(crystalId) ? prev.filter((id) => id !== crystalId) : [...prev, crystalId]
    )
  }

  const handleSelectAllCrystals = (checked) => {
    setSelectedCrystals(checked ? items.map((item) => item.crystal_id) : [])
  }

  const handleBulkDeleteCrystals = async () => {
    if (selectedCrystals.length === 0) return
    if (!confirm(`Delete ${selectedCrystals.length} selected crystal structures?`)) return
    let failed = 0
    for (const id of selectedCrystals) {
      try {
        await deleteMutation.mutateAsync(id)
      } catch {
        failed += 1
      }
    }
    if (selectedCrystalId && selectedCrystals.includes(selectedCrystalId)) setSelectedCrystalId(null)
    setSelectedCrystals([])
    execute()
    notify(
      failed > 0 ? 'error' : 'success',
      failed > 0
        ? `${selectedCrystals.length - failed} deleted, ${failed} failed`
        : `${selectedCrystals.length} deleted`
    )
  }

  const handleBatchGenerate = () => {
    setBatchResult(null)
    batchGenerateMutation.mutate(
      {
        material,
        surface: null,
        thickness_angstrom: Number(thickness),
        xy_min: 35.0,
        xy_max: 60.0,
        hydroxylated,
        hydroxyl_density: Number(hydroxylDensity),
      },
      {
        onSuccess: (result) => {
          if (result && Array.isArray(result.sizes)) {
            setBatchResult(result)
          }
          execute()
          notify(
            'success',
            `${result?.material || material} (${result?.surface || '?'}): ${result?.generated_count ?? 0} generated, ${result?.skipped_count ?? 0} skipped`
          )
        },
        onError: (err) => {
          notify('error', err?.response?.data?.detail || err?.message || 'Batch generation failed')
        },
      }
    )
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
          assetType="crystal_structures"
        />

        {showCreatePanel && (
          <CrystalCreatePanel
            material={material}
            setMaterial={setMaterial}
            thickness={thickness}
            setThickness={setThickness}
            hydroxylated={hydroxylated}
            setHydroxylated={setHydroxylated}
            hydroxylDensity={hydroxylDensity}
            setHydroxylDensity={setHydroxylDensity}
            crystalInfo={crystalInfo}
            materialElements={materialElements}
            unitPreview={unitPreview}
            batchGenerateMutation={batchGenerateMutation}
            handleBatchGenerate={handleBatchGenerate}
            batchResult={batchResult}
            setBatchResult={setBatchResult}
            selectedCrystalId={selectedCrystalId}
            setSelectedCrystalId={setSelectedCrystalId}
            preview={preview}
            previewLoading={previewLoading}
          />
        )}
      </div>

      {/* Scrollable content area */}
      {showLibraryPanel && (
        <div className="flex-1 overflow-auto min-h-0 mt-4">
          <div className="grid gap-4 md:grid-cols-[6fr_4fr]">
            <CrystalLibraryPanel
              items={items}
              loading={loading}
              execute={execute}
              selectedCrystalId={selectedCrystalId}
              setSelectedCrystalId={setSelectedCrystalId}
              selectedCrystals={selectedCrystals}
              selectedCrystalSet={selectedCrystalSet}
              toggleSelectCrystal={toggleSelectCrystal}
              handleSelectAllCrystals={handleSelectAllCrystals}
            />

            <CrystalDetailPanel
              selectedCrystalId={selectedCrystalId}
              selectedCrystal={selectedCrystal}
              preview={preview}
              previewLoading={previewLoading}
              previewErrorMessage={previewErrorMessage}
              previewAtomTypes={previewAtomTypes}
              representation={representation}
              setRepresentation={setRepresentation}
              refreshPreview={refreshPreview}
              libraryCellMetrics={libraryCellMetrics}
            />
          </div>
        </div>
      )}

      {/* Fixed bottom selection action bar */}
      {selectedCrystals.length > 0 && (
        <div className="fixed bottom-0 left-72 right-0 z-40 flex items-center gap-3 px-4 py-2.5 bg-slate-800 border-t border-slate-700">
          <span className="text-xs text-slate-300">{selectedCrystals.length} selected</span>
          <button
            onClick={handleBulkDeleteCrystals}
            className="px-3 py-1 rounded text-xs font-medium bg-red-600 hover:bg-red-700 text-white flex items-center gap-1"
          >
            <Trash2 className="w-3 h-3" />
            Delete Selected
          </button>
          <button
            onClick={() => setSelectedCrystals([])}
            className="px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-200"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}

export default CrystalStructuresPage
