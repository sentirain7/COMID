import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Database, Loader2, AlertCircle, ChevronDown, Search } from 'lucide-react'
import clsx from 'clsx'
import { useMolecules } from '../hooks/useMolecules'
import { useEIntraLive } from '../hooks/useEIntraLive'
import { getMoleculeStructure } from '../api/client'
import { extractElementsFromXyz } from './molecule-viewer'
import { MoleculeTable } from './molecules/MoleculeTable'
import { MoleculePreviewPanel } from './molecules/MoleculePreviewPanel'
import { PAGE_TAB_CONFIG, TAB_CONFIG, AGING_TAB_CONFIG, inferSourceKey } from './molecules/helpers'
import DynamicsPanel from './molecules/DynamicsPanel'
import {
  useAdminArtifactStatus,
  useAdminGenerateArtifact,
  useAdminGenerateAll,
  useAdminGenerateSelected,
  useAdminCancelBatch,
  useAdminResetBatch,
  useAdminDiagnoseArtifact,
  useAdminBatchProgress,
} from '../hooks/useApi'
import { useDeleteArtifact, useDeleteEIntra } from '../hooks/useArtifacts'
import { useNotification } from '../hooks/useNotification'
import AdminBatchProgress from './ff-parameters/AdminBatchProgress'
import ScanDatabaseModal from './ScanDatabaseModal'
import { HEADER_ACTION_BUTTON } from './shared/headerActionStyles'
import {
  getSubmissionEIntraMethodLabel,
  SUBMISSION_E_INTRA_METHOD_OPTIONS,
} from '../lib/eIntraMethod'
import { useSubmissionEIntraMethod } from '../hooks/useSubmissionEIntraMethod'

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center p-12">
      <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
      <span className="ml-3 text-slate-400">Loading molecules...</span>
    </div>
  )
}

function ErrorMessage({ message, onRetry }) {
  return (
    <div className="card p-8 text-center">
      <AlertCircle className="w-12 h-12 text-red-400 mx-auto" />
      <p className="text-red-400 mt-4">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 px-4 py-2 bg-blue-500/20 text-blue-400 rounded hover:bg-blue-500/30 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  )
}

function Molecules() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialMolIdParam = searchParams.get('mol_id') || ''
  const [activePageTab, setActivePageTab] = useState('library')
  const [activeTab, setActiveTab] = useState('asphalt_binder')
  const [activeAgingTab, setActiveAgingTab] = useState('non_aging')
  // PR 2 (Method 1a SSOT, Codex Round 7): user-selectable E_intra method
  // for the coverage view.  v01.04.17: Now syncs with server settings via
  // useSubmissionEIntraMethod hook instead of hardcoding Method 1 baseline.
  const {
    effectiveEIntraMethod: eIntraMethod,
    setSelectedEIntraMethod: setEIntraMethod,
  } = useSubmissionEIntraMethod()
  const [librarySelectedMolId, setLibrarySelectedMolId] = useState(initialMolIdParam)
  const [dynamicsSelectedMolId, setDynamicsSelectedMolId] = useState('')
  // Convenience alias: routes the active tab to the correct state pair.
  const selectedMolId = activePageTab === 'dynamics' ? dynamicsSelectedMolId : librarySelectedMolId
  const setSelectedMolId = activePageTab === 'dynamics' ? setDynamicsSelectedMolId : setLibrarySelectedMolId
  const [previewData, setPreviewData] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [representation, setRepresentation] = useState('ball_and_stick')
  const [checkedMolIds, setCheckedMolIds] = useState(() => new Set())
  const [scanModalOpen, setScanModalOpen] = useState(false)
  // v00.99.71: operation ownership — loading state is owned by the op that
  // started the fetch. `kind` distinguishes library selection fetch from
  // upload validation so one cannot silently invalidate the other's finally.
  // `previewAbortController` is only set while a network call is in flight.
  const previewOp = useRef({ id: 0, kind: null })
  const previewAbortController = useRef(null)

  // Fetch full molecule set once and filter on client to avoid data loss across tabs.
  // PR 2 (Codex Round 7): forward eIntraMethod so the coverage view follows
  // the user's selected E_intra method.
  const { molecules, loading, error, total, refetch } = useMolecules({
    limit: 5000,
    eIntraMethod,
  })

  // PR 2 (Method 1a SSOT, Codex Round 6+8): subscribe to live E_intra
  // events for the visible molecules so the coverage badge in the table
  // refreshes when a Method 1 / 1a row lands.  ``useEIntraLive`` already
  // partitions React Query invalidations per (molId, method, temperatureK).
  // Round 8: scope the subscription to visible mol_ids so we do not stream
  // every binder/single-molecule update through the page when only a few
  // are rendered.  ``useEIntraLive`` accepts ``null`` for "all", so we
  // compute the visible slice here and pass it down.
  // Note: ``filteredMolecules`` is computed below; deriving the id list
  // there once it exists keeps the subscription tight.

  // v00.99.66: submit screens deep-link to /molecules?mol_id=... when a
  // selected molecule is blocked (artifact missing). Auto-switch the active
  // source/aging tab so the chip is visible, then clear the URL param so
  // further navigation within /molecules is not sticky.
  useEffect(() => {
    if (!initialMolIdParam) return
    const mol = molecules.find((m) => m.mol_id === initialMolIdParam)
    if (!mol) {
      if (molecules.length > 0) {
        const next = new URLSearchParams(searchParams)
        next.delete('mol_id')
        setSearchParams(next, { replace: true })
      }
      return
    }
    const sourceKey = inferSourceKey(mol)
    if (sourceKey) setActiveTab(sourceKey)
    if (sourceKey === 'asphalt_binder' && mol.aging_state) {
      setActiveAgingTab(mol.aging_state)
    }
    setLibrarySelectedMolId(initialMolIdParam)
    setActivePageTab('library')
    const next = new URLSearchParams(searchParams)
    next.delete('mol_id')
    setSearchParams(next, { replace: true })
  }, [molecules, initialMolIdParam, searchParams, setSearchParams])

  // FF admin hooks (always called unconditionally for React hook order)
  const adminStatus = useAdminArtifactStatus(true)
  const generateMutation = useAdminGenerateArtifact()
  const generateAllMutation = useAdminGenerateAll()
  const generateSelectedMutation = useAdminGenerateSelected()
  const cancelBatchMutation = useAdminCancelBatch()
  const resetBatchMutation = useAdminResetBatch()
  const diagnoseMutation = useAdminDiagnoseArtifact()
  const deleteArtifactMutation = useDeleteArtifact()
  const deleteEIntraMutation = useDeleteEIntra()
  // Batch progress: initial fetch always runs, but 3s polling only when
  // batch is actually running (controlled inside the hook via refetchInterval).
  const progress = useAdminBatchProgress(true)
  const { notification: ffNotification, notify: ffNotify, dismiss: ffDismiss } = useNotification(8000)
  // v00.99.57: Since the ProfileSelector was removed from the Single Molecule
  // page, the regular "Generate All Pending" path always starts with baseline.
  // sqm_robust retry is (1) performed by the auto-retry logic in the batch
  // runner and (2) manually triggered per molecule via the "Retry (Robust)"
  // button in MoleculePreviewPanel.
  const ffProfile = 'baseline'
  const [forceRegen, setForceRegen] = useState(false)
  const [batchDismissed, setBatchDismissed] = useState(false)

  const tabCounts = useMemo(() => {
    const counts = Object.fromEntries(TAB_CONFIG.map((tab) => [tab.key, 0]))
    molecules.forEach((mol) => {
      const sourceKey = inferSourceKey(mol)
      counts[sourceKey] = (counts[sourceKey] || 0) + 1
    })
    return counts
  }, [molecules])

  const asphaltAgingCounts = useMemo(() => {
    const counts = { non_aging: 0, short_aging: 0, long_aging: 0 }
    molecules.forEach((mol) => {
      if (inferSourceKey(mol) !== 'asphalt_binder') return
      const aging = mol.aging_state || 'non_aging'
      counts[aging] = (counts[aging] || 0) + 1
    })
    return counts
  }, [molecules])

  // Apply tab + aging + search filters (client-side)
  const filteredMolecules = useMemo(() => {
    const sourceMolecules = molecules.filter((mol) => inferSourceKey(mol) === activeTab)
    if (activeTab !== 'asphalt_binder') {
      return sourceMolecules
    }
    return sourceMolecules.filter((mol) => mol.aging_state === activeAgingTab)
  }, [molecules, activeTab, activeAgingTab])

  // PR 2 (Codex Round 8): narrow the live subscription to currently
  // visible molecules so a Method 1a write to molecule X does not
  // refetch the full molecule list when only a few rows are rendered.
  const visibleMolIds = useMemo(
    () => filteredMolecules.map((m) => m.mol_id),
    [filteredMolecules],
  )
  useEIntraLive(visibleMolIds.length > 0 ? visibleMolIds : null)

  const selectedMolecule = useMemo(
    () => filteredMolecules.find((mol) => mol.mol_id === selectedMolId) || null,
    [filteredMolecules, selectedMolId]
  )

  // NOTE: selectedMolAdminRow is derived from adminRowMap below so the Preview
  // panel uses the *exact same* mapping as MoleculeTable (SSOT).

  useEffect(() => {
    // Only correct Library selection — Dynamics has its own state.
    if (activePageTab !== 'library') return
    if (
      initialMolIdParam &&
      molecules.some((mol) => mol.mol_id === initialMolIdParam)
    ) {
      return
    }
    if (filteredMolecules.length === 0) {
      setLibrarySelectedMolId('')
      return
    }
    if (!filteredMolecules.some((mol) => mol.mol_id === librarySelectedMolId)) {
      setLibrarySelectedMolId(filteredMolecules[0].mol_id)
    }
  }, [activePageTab, filteredMolecules, initialMolIdParam, molecules, librarySelectedMolId])

  const fetchPreview = useCallback(async (molId) => {
    // Always cancel whatever is in flight; we're taking over the panel.
    previewAbortController.current?.abort()
    previewAbortController.current = null

    // Falsy selection: clear panel without starting a new op.
    // Must reset previewLoading here — otherwise a stale `true` from a
    // previously-aborted fetch can leave the spinner spinning forever.
    if (!molId) {
      previewOp.current = { id: previewOp.current.id + 1, kind: null }
      setPreviewData(null)
      setPreviewError('')
      setPreviewLoading(false)
      return
    }

    const opId = previewOp.current.id + 1
    previewOp.current = { id: opId, kind: 'library' }
    const controller = new AbortController()
    previewAbortController.current = controller

    // Clear stale structure immediately so the new molecule's metadata
    // (badges, atom count) is never shown against the previous xyz.
    setPreviewData(null)
    setPreviewError('')
    setPreviewLoading(true)

    try {
      const data = await getMoleculeStructure(molId, controller.signal)
      if (previewOp.current.id !== opId) return
      setPreviewData({
        xyz: data?.xyz || '',
        bonds: data?.bonds || [],
        atomCount: data?.atom_count || 0,
        elements: data?.elements || [],
        hasFormalCharges: data?.has_formal_charges || false,
        formalChargeSum: data?.formal_charge_sum || 0,
        ffAvailable: data?.ff_available || false,
        ffCheckMessage: data?.ff_check_message || '',
      })
    } catch (err) {
      if (err?.name === 'AbortError' || err?.name === 'CanceledError') return
      if (previewOp.current.id !== opId) return
      setPreviewData(null)
      setPreviewError(err?.response?.data?.detail || err?.message || 'Failed to load structure')
    } finally {
      if (previewOp.current.id === opId) {
        setPreviewLoading(false)
        if (previewAbortController.current === controller) {
          previewAbortController.current = null
        }
      }
    }
  }, [])

  const previewElements = useMemo(
    () => previewData?.elements?.length ? previewData.elements : extractElementsFromXyz(previewData?.xyz),
    [previewData?.elements, previewData?.xyz]
  )

  const adminRowMap = useMemo(() => {
    if (!adminStatus.data?.rows) return new Map()
    const map = new Map()
    for (const row of adminStatus.data.rows) {
      for (const cid of row.consumer_ids || []) {
        map.set(cid, row)
      }
      // Also index by source_id so molecules whose mol_id matches the source
      // (e.g. saturates where mol_id == source_id) resolve the same row.
      if (row.source_id) {
        map.set(row.source_id, row)
      }
    }
    // v00.99.63: removed the regex strip fallback (v00.99.61). The server's
    // _build_consumer_index registers temp_code variants (e.g. U-RE-Thio-0293)
    // exactly in consumer_ids, so the consumer_ids loop above already matches
    // them precisely. No heuristic needed.
    return map
  }, [adminStatus.data])

  // SSOT: selectedMolAdminRow uses the same map as MoleculeTable's FFRouteBadge
  const selectedMolAdminRow = useMemo(
    () => (selectedMolId ? adminRowMap.get(selectedMolId) || null : null),
    [selectedMolId, adminRowMap],
  )

  // Dynamic bottom padding based on active docks.
  // v00.99.66: Adjusted heights for accurate measurements:
  //   - SelectionActionBar: py-2.5 (20px) + content (~28px) + border = ~50px
  //   - AdminBatchProgress dock: py-2 (16px) + p-3 (24px) + rows (~70px) = ~110px
  // v00.99.81-88 bottom-gap iterations: 24 → 6 → 1 (touched) → 8 (too far)
  // v00.99.89: 8 → 3. User wants panel extended close to the active-bar
  //   border-t line without touching it. 3 px is just enough separation
  //   to keep the edges visually distinct while reclaiming 5 px of
  //   vertical space for the table/preview content. The +50 / +110
  //   dock reserves remain untouched so overlap is impossible.
  // bottomPadding removed — admin dock and selection bar are now flex
  // children (not position:fixed), so the flex-1 content area auto-shrinks.

  // v00.99.71: preview refetch is keyed strictly on the selected molecule id.
  // - FF badge (`ffReady/ffLabel` in MoleculePreviewPanel) reads
  //   `selectedMolAdminRow` directly, so adminRow changes are reflected without
  //   a structure refetch.
  // - `ffCheckMessage` (server-rendered text) no longer auto-updates mid-batch;
  //   the manual Refresh button in the panel can be used to resync it.
  // Removing `artifact_status/generation_profile` from deps also eliminates
  // the abort/re-fetch loop triggered by background admin status polling.
  useEffect(() => {
    fetchPreview(selectedMolecule?.mol_id)

    return () => {
      previewAbortController.current?.abort()
    }
  }, [selectedMolecule?.mol_id, fetchPreview])

  const handleGenerate = useCallback((sourceId) => {
    generateMutation.mutate(
      { molId: sourceId, profile: ffProfile },
      {
        onSuccess: () => ffNotify('success', `Generated artifact for ${sourceId}`),
        onError: (err) => ffNotify('error', err?.response?.data?.detail?.message || err.message),
      }
    )
  }, [generateMutation, ffProfile, ffNotify])



  const handleGenerateAll = useCallback(() => {
    setBatchDismissed(false)
    generateAllMutation.mutate(
      { profile: ffProfile, force: forceRegen },
      {
        onSuccess: (data) => ffNotify('info', `Batch started: ${data.eligible_count || 0} molecules${forceRegen ? ' (force)' : ''}`),
        onError: (err) => ffNotify('error', err?.response?.data?.detail?.message || err.message),
      }
    )
  }, [generateAllMutation, ffProfile, forceRegen, ffNotify])

  const handleToggleChecked = useCallback((molId, forceState) => {
    setCheckedMolIds((prev) => {
      const next = new Set(prev)
      if (forceState === false) {
        next.delete(molId)
      } else if (forceState === true) {
        next.add(molId)
      } else {
        next.has(molId) ? next.delete(molId) : next.add(molId)
      }
      return next
    })
  }, [])

  const handleGenerateSelected = useCallback(() => {
    const molIds = Array.from(checkedMolIds)
    if (molIds.length === 0) return
    generateSelectedMutation.mutate(
      { molIds, profile: ffProfile, force: forceRegen },
      {
        onSuccess: (data) => {
          const n = data?.eligible_count ?? 0
          const skippedItems = data?.skipped || []
          const unmatched = data?.unmatched_mol_ids || []
          const skipCount = skippedItems.length + unmatched.length
          // Surface the first skip reason so the operator can distinguish
          // a UI/SSOT bug (unmatched = server thinks it's complete) from a
          // policy gate (skipped = lock/cooldown/etc) without opening DevTools.
          const firstReason = (() => {
            if (skippedItems[0]) {
              const id = skippedItems[0].mol_id || ''
              const msg = skippedItems[0].message || 'policy gate'
              return id ? `${id}: ${msg}` : msg
            }
            if (unmatched[0]) {
              return `${unmatched[0]} (complete / non-organic / mol_id mismatch)`
            }
            return ''
          })()
          if (n > 0) {
            const suffix = skipCount
              ? ` (${skipCount} skipped${firstReason ? ` — ${firstReason}` : ''})`
              : ''
            ffNotify('info', `Selected batch started: ${n} molecule(s)${suffix}`)
          } else {
            const detail = firstReason ? ` — ${firstReason}` : ''
            ffNotify('warning', `Nothing eligible in selection${detail}`)
          }
        },
        onError: (err) => ffNotify('error', err?.response?.data?.detail?.message || err.message),
      }
    )
  }, [checkedMolIds, ffProfile, forceRegen, generateSelectedMutation, ffNotify])

  // Classify checked molecules by FF status for smart action bar
  const checkedSummary = useMemo(() => {
    const ready = [], failed = [], pending = [], withEIntra = [], withArtifact = [], withResettable = []
    for (const m of filteredMolecules) {
      if (!checkedMolIds.has(m.mol_id)) continue
      const row = adminRowMap.get(m.mol_id)
      if (m.is_artifact_complete || row?.artifact_status === 'complete') {
        ready.push(m)
      } else if (row?.artifact_status === 'failed') {
        failed.push(m)
      } else {
        pending.push(m)
      }
      if (m.e_intra_coverage?.computed_count > 0) withEIntra.push(m)
      if (m.is_artifact_complete) withArtifact.push(m)
      // v01.02.05: include failed artifacts in resettable list (sidecar-only delete)
      if (row?.artifact_status === 'failed') withResettable.push(m)
    }
    return { ready, failed, pending, withEIntra, withArtifact, withResettable }
  }, [checkedMolIds, filteredMolecules, adminRowMap])

  // PR 2 (Codex Round 7): default delete is method-scoped to the currently
  // selected E_intra method.  This matches the new backend contract where
  // a method-scoped delete is the safe default; "delete all methods" stays
  // available as an explicit confirmation flow.
  const handleDeleteEIntraSelected = useCallback(async () => {
    const targets = checkedSummary.withEIntra.map((m) => m.mol_id)
    if (!targets.length) return
    let ok = 0; let fail = 0
    for (const molId of targets) {
      try {
        await deleteEIntraMutation.mutateAsync({ molId, eIntraMethod })
        ok++
      } catch {
        fail++
      }
    }
    ffNotify(
      fail ? 'warning' : 'success',
      `E_intra [${getSubmissionEIntraMethodLabel(eIntraMethod)}] deleted: ${ok} ok, ${fail} failed`,
    )
  }, [checkedSummary.withEIntra, deleteEIntraMutation, eIntraMethod, ffNotify])

  const handleDeleteEIntraAllMethodsSelected = useCallback(async () => {
    // Explicit "delete every method" confirmation flow.
    const targets = checkedSummary.withEIntra.map((m) => m.mol_id)
    if (!targets.length) return
    if (!window.confirm(
      `Delete E_intra rows for ${targets.length} molecule(s) across ALL methods? `
      + `This wipes all stored E_intra caches and cannot be undone.`,
    )) {
      return
    }
    let ok = 0; let fail = 0
    for (const molId of targets) {
      try {
        await deleteEIntraMutation.mutateAsync({ molId, allMethods: true })
        ok++
      } catch {
        fail++
      }
    }
    ffNotify(
      fail ? 'warning' : 'success',
      `E_intra (all methods) deleted: ${ok} ok, ${fail} failed`,
    )
  }, [checkedSummary.withEIntra, deleteEIntraMutation, ffNotify])

  const handleDeleteFFAndEIntraSelected = useCallback(async () => {
    const targets = checkedSummary.withArtifact.map((m) => m.mol_id)
    if (!targets.length) return
    if (!window.confirm(
      `Delete FF artifacts and ALL E_intra rows for ${targets.length} molecule(s)? `
      + `This wipes all stored E_intra caches and cannot be undone.`,
    )) {
      return
    }
    let ok = 0; let fail = 0
    for (const molId of targets) {
      // Delete E_intra first (if any), then FF artifact.  When force-
      // deleting the FF artifact, also wipe every method cache to avoid
      // orphaned rows pointing at a deleted artifact.
      try {
        await deleteEIntraMutation.mutateAsync({ molId, allMethods: true })
      } catch { /* no E_intra is ok */ }
      try {
        // force=true: delete even if source_id is shared by multiple consumers
        await deleteArtifactMutation.mutateAsync({ molId, force: true })
        ok++
      } catch {
        fail++
      }
    }
    ffNotify(fail ? 'warning' : 'success', `FF+E_intra deleted: ${ok} ok, ${fail} failed`)
  }, [checkedSummary.withArtifact, deleteArtifactMutation, deleteEIntraMutation, ffNotify])

  // v01.02.05: reset failed artifacts to pending state (sidecar-only delete)
  const handleResetFailedSelected = useCallback(async () => {
    const targets = checkedSummary.withResettable.map((m) => m.mol_id)
    if (!targets.length) return
    let ok = 0; let fail = 0
    for (const molId of targets) {
      try {
        await deleteArtifactMutation.mutateAsync({ molId, force: true })
        ok++
      } catch {
        fail++
      }
    }
    ffNotify(fail ? 'warning' : 'success', `Failed FF reset: ${ok} ok, ${fail} failed`)
  }, [checkedSummary.withResettable, deleteArtifactMutation, ffNotify])

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorMessage message={error} onRetry={refetch} />

  // v00.99.83: outer height corrected from calc(100vh - 8rem) to
  // calc(100vh - 88px). 8rem = 128 px overcounted the top offset (it
  // double-subtracted the fixed Header's height: `mt-16` on <main> already
  // reserves the Header's 64 px). The real top offset is Header (64 px,
  // fixed) → `mt-16` clears it → + main's `p-6` top (24 px) = 88 px.
  // Using 128 px left the panel bottom 40 px above the viewport bottom,
  // which the bottomPadding math could not compensate for. With 88 px the
  // panel bottom reaches the viewport bottom and bottomPadding=1+dock
  // correctly yields a 1 px hairline above the active bar's border.
  return (
    <div className="h-[calc(100vh-88px)] flex flex-col">
      {/* Fixed top area: header, batch ops, tabs, filters */}
      <div className="flex-shrink-0 space-y-4">
        {/* Header — v00.99.57: ProfileSelector removed. Batch path is always
            baseline; sqm_robust escalation is handled automatically by the
            runner and exposed on a per-mol "Retry (Robust)" button. */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Single Molecule - FF Parameterization</h1>
            <p className="text-slate-400 text-sm mt-1">
              Browse molecules loaded from the unified library ({total} total).
            </p>
          </div>
          <button
            onClick={() => setScanModalOpen(true)}
            className={HEADER_ACTION_BUTTON}
          >
            <Search className="w-4 h-4" />
            Scan Database
          </button>
        </div>

        {/* Page-level tabs: Library / Dynamics */}
        <div className="flex gap-1 border-b border-slate-700">
          {PAGE_TAB_CONFIG.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActivePageTab(tab.key)}
              className={clsx(
                'px-4 py-1.5 text-sm font-medium transition-colors',
                activePageTab === tab.key
                  ? 'text-blue-300 border-b-2 border-blue-500'
                  : 'text-slate-400 hover:text-slate-200 border-b-2 border-transparent',
              )}
              aria-pressed={activePageTab === tab.key}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Fixed top-right toast (out of flow — no layout shift).
            Inline/shared-bottom NotificationBanner both push content around;
            this stays completely independent of the page flex layout
            and never overlaps the SelectionActionBar (fixed bottom). */}
        {ffNotification && (
          <div
            role={ffNotification.type === 'error' ? 'alert' : 'status'}
            aria-live={ffNotification.type === 'error' ? 'assertive' : 'polite'}
            className={clsx(
              'fixed top-20 right-4 max-w-md z-50 shadow-lg rounded border px-3 py-2 text-sm flex items-center justify-between',
              {
                error: 'border-red-500/40 bg-red-500/10 text-red-200',
                warning: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
                info: 'border-blue-500/40 bg-blue-500/10 text-blue-200',
                success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
              }[ffNotification.type] || 'border-slate-500/40 bg-slate-500/10 text-slate-200',
            )}
            data-testid="molecules-notification"
          >
            <span>{ffNotification.message}</span>
            <button
              type="button"
              onClick={ffDismiss}
              className="ml-2 text-xs opacity-70 hover:opacity-100"
              data-testid="molecules-notification-dismiss"
              aria-label="dismiss notification"
            >
              ✕
            </button>
          </div>
        )}

        {/* v00.99.56: FF Batch Operations row removed — ProfileSelector moved
            to the header, Generate All Pending moved to the results-count row.
            AdminBatchProgress moved to a fixed dock above the selection action
            bar (see bottom of the page). */}

        {/* Library tab content — category tabs, action bar, batch progress */}
        {activePageTab === 'library' && <>
        {/* Category Tabs (with inline Aging sub-tabs under Asphalt Binder) */}
        <div className="card p-3 space-y-2">
          <div className="flex flex-wrap gap-2">
            {TAB_CONFIG.map((tab) => {
              const isActive = activeTab === tab.key
              const isExpandable = tab.key === 'asphalt_binder' && isActive
              return (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={clsx(
                    'px-3 py-1.5 rounded text-sm border transition-colors flex items-center gap-1',
                    isActive
                      ? 'bg-blue-500/20 border-blue-500/60 text-blue-300'
                      : 'bg-slate-700/40 border-slate-600 text-slate-300 hover:bg-slate-700'
                  )}
                  aria-pressed={isActive}
                >
                  <span>{tab.label} ({tabCounts[tab.key] || 0})</span>
                  {isExpandable && <ChevronDown className="w-3 h-3" />}
                </button>
              )
            })}
          </div>

          {/* Aging sub-tabs — always rendered to prevent layout shift; invisible when parent tab != asphalt_binder */}
          <div
            className={clsx(
              'flex items-center gap-2 pl-3',
              activeTab !== 'asphalt_binder' && 'invisible pointer-events-none'
            )}
            aria-hidden={activeTab !== 'asphalt_binder'}
          >
            <span className="text-slate-500 text-sm select-none" aria-hidden="true">╰─</span>
            <div className="flex flex-wrap gap-1.5">
              {AGING_TAB_CONFIG.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveAgingTab(tab.key)}
                  disabled={activeTab !== 'asphalt_binder'}
                  tabIndex={activeTab === 'asphalt_binder' ? 0 : -1}
                  className={clsx(
                    'px-2.5 py-1 rounded-full text-xs border transition-colors',
                    activeAgingTab === tab.key
                      ? 'bg-blue-500/25 border-blue-400/60 text-blue-200'
                      : 'bg-slate-800/60 border-slate-600 text-slate-400 hover:bg-slate-700'
                  )}
                  aria-pressed={activeAgingTab === tab.key}
                >
                  {tab.label} ({asphaltAgingCounts[tab.key] || 0})
                </button>
              ))}
            </div>
          </div>
          {/* PR 2 (Method 1a SSOT, Codex Round 7): user-facing E_intra
              method selector.  Drives the molecule list query so the
              coverage badge / matrix reflects the selected method. */}
          <div className="flex items-center gap-2 pl-3">
            <span className="text-slate-500 text-xs select-none" aria-hidden="true">
              Coverage method:
            </span>
            <select
              className="px-2 py-1 rounded text-xs bg-slate-800 border border-slate-600 text-slate-200"
              value={eIntraMethod}
              onChange={(e) => setEIntraMethod(e.target.value)}
              aria-label="Select E_intra method for coverage view"
            >
              {SUBMISSION_E_INTRA_METHOD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* v00.99.58: removed the "Showing N molecules in …" description.
            The count is already shown on the tabs, so it was redundant. Only
            the Generate All Pending + Validate MOL actions are left here, left-aligned. */}
        {/* Action bar + batch progress — grid-aligned with table [6fr_4fr]
            so the progress bar right edge matches the table right edge. */}
        <div className="grid gap-4 md:grid-cols-[6fr_4fr]">
          <div className="flex items-center gap-2">
            <label className="inline-flex items-center gap-1 text-xs text-slate-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={forceRegen}
                onChange={(e) => setForceRegen(e.target.checked)}
                className="rounded border-slate-600 bg-slate-700 text-amber-500 focus:ring-amber-500/30 w-3.5 h-3.5"
              />
              Force
            </label>
            <button
              onClick={handleGenerateAll}
              disabled={generateAllMutation.isPending}
              className={clsx(
                'px-3 py-1 rounded text-xs font-medium text-white disabled:opacity-40',
                forceRegen ? 'bg-amber-600 hover:bg-amber-500' : 'bg-emerald-700 hover:bg-emerald-600',
              )}
            >
              {forceRegen ? 'Regenerate All (Force)' : 'Generate All Pending'}
            </button>
            {/* Selection actions — appear when checkboxes are checked */}
            {checkedMolIds.size > 0 && (() => {
              const { ready, failed, pending, withEIntra, withArtifact, withResettable } = checkedSummary
              const genTarget = forceRegen ? checkedMolIds.size : failed.length + pending.length
              const batchBusy = generateSelectedMutation.isPending ||
                (progress.data?.running && progress.data?.batch_kind === 'admin')
              return (
                <>
                  <span className="text-slate-600 mx-1">|</span>
                  <span className="text-[11px] text-slate-300 flex-shrink-0 flex items-center gap-1">
                    {checkedMolIds.size} selected
                    {ready.length > 0 && <span className="text-emerald-400">●{ready.length}</span>}
                    {failed.length > 0 && <span className="text-red-400">●{failed.length}</span>}
                    {pending.length > 0 && <span className="text-slate-400">●{pending.length}</span>}
                  </span>
                  {genTarget > 0 && (
                    <button
                      onClick={handleGenerateSelected}
                      disabled={batchBusy}
                      className={clsx(
                        'px-3 py-1 rounded text-xs font-medium text-white disabled:opacity-40 flex items-center gap-1',
                        forceRegen ? 'bg-amber-600 hover:bg-amber-500' : 'bg-emerald-700 hover:bg-emerald-600',
                      )}
                    >
                      {generateSelectedMutation.isPending && <Loader2 className="w-3 h-3 animate-spin" />}
                      {forceRegen ? `Regen (${genTarget})` : `Generate (${genTarget})`}
                    </button>
                  )}
                  {withEIntra.length > 0 && (
                    <>
                      <button
                        onClick={handleDeleteEIntraSelected}
                        disabled={deleteEIntraMutation.isPending}
                        className="px-3 py-1 rounded text-xs font-medium bg-red-700/80 hover:bg-red-600 text-white disabled:opacity-40 flex items-center gap-1"
                        title={`Delete only the currently selected method (${eIntraMethod})`}
                      >
                        {deleteEIntraMutation.isPending && <Loader2 className="w-3 h-3 animate-spin" />}
                        Del E_intra ({withEIntra.length})
                      </button>
                      <button
                        onClick={handleDeleteEIntraAllMethodsSelected}
                        disabled={deleteEIntraMutation.isPending}
                        className="px-3 py-1 rounded text-xs font-medium bg-red-900/80 hover:bg-red-800 text-white disabled:opacity-40 flex items-center gap-1"
                        title="Delete every method's E_intra rows for the selected molecules (requires confirmation)"
                      >
                        Del E_intra (all methods)
                      </button>
                    </>
                  )}
                  {withArtifact.length > 0 && (
                    <button
                      onClick={handleDeleteFFAndEIntraSelected}
                      disabled={deleteArtifactMutation.isPending}
                      className="px-3 py-1 rounded text-xs font-medium bg-red-800/80 hover:bg-red-700 text-white disabled:opacity-40 flex items-center gap-1"
                    >
                      {deleteArtifactMutation.isPending && <Loader2 className="w-3 h-3 animate-spin" />}
                      Delete FF + E_intra ({withArtifact.length})
                    </button>
                  )}
                  {/* v01.02.05: reset failed artifacts to pending state */}
                  {withResettable.length > 0 && (
                    <button
                      onClick={handleResetFailedSelected}
                      disabled={deleteArtifactMutation.isPending}
                      className="px-3 py-1 rounded text-xs font-medium bg-orange-700/80 hover:bg-orange-600 text-white disabled:opacity-40 flex items-center gap-1"
                    >
                      {deleteArtifactMutation.isPending && <Loader2 className="w-3 h-3 animate-spin" />}
                      Reset Failed ({withResettable.length})
                    </button>
                  )}
                  <button
                    onClick={() => setCheckedMolIds(new Set())}
                    className="px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-200"
                  >
                    Clear
                  </button>
                </>
              )
            })()}
            {/* Batch progress — fills remaining space in the 6fr column */}
            {!batchDismissed && progress.data &&
              (progress.data.batch_kind === 'admin' || progress.data.running) && (
                <div className="flex-1 min-w-0 ml-4" data-testid="admin-batch-progress-dock">
                  <AdminBatchProgress
                    progress={progress.data}
                    onCancel={() => cancelBatchMutation.mutate()}
                    cancelDisabled={cancelBatchMutation.isPending}
                    onReset={() => resetBatchMutation.mutate()}
                    resetDisabled={resetBatchMutation.isPending}
                    onDismiss={() => setBatchDismissed(true)}
                  />
                </div>
              )}
          </div>
        </div>
        </>}
      </div>

      {/* Content area — switches between Library and Dynamics */}
      {activePageTab === 'library' && (
        <div className="flex-1 overflow-hidden min-h-0 mt-4">
          {filteredMolecules.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-[6fr_4fr] h-full">
              <MoleculeTable
                molecules={filteredMolecules}
                selectedMolId={selectedMolId}
                onSelectMolId={setSelectedMolId}
                adminRowMap={adminRowMap}
                checkedMolIds={checkedMolIds}
                onToggleChecked={handleToggleChecked}
              />

              <div className="h-full min-h-0">
                <MoleculePreviewPanel
                  selectedMolecule={selectedMolecule}
                  previewData={previewData}
                  previewLoading={previewLoading}
                  previewError={previewError}
                  previewElements={previewElements}
                  representation={representation}
                  onRepresentationChange={setRepresentation}
                  onRefresh={() => fetchPreview(selectedMolecule?.mol_id)}
                  ffAdminRow={selectedMolAdminRow}
                  onGenerate={handleGenerate}
                  onDiagnose={(molId) => {
                    // useAdminDiagnoseArtifact's mutationFn is `(molId) =>
                    // adminDiagnoseArtifact(molId)` — pass the string directly.
                    // (Passing `{ molId }` makes encodeURIComponent stringify
                    // the object into "[object Object]" and breaks the URL.)
                    diagnoseMutation.mutate(molId, {
                      onSuccess: (data) => ffNotify('info', `Diagnose: ${data.verdict}`),
                      onError: (err) => ffNotify('error', err.message),
                    })
                  }}
                  generatingId={generateMutation.isPending ? generateMutation.variables?.molId : null}
                />
              </div>
            </div>
          ) : (
            <div className="card p-12 text-center">
              <Database className="w-12 h-12 text-slate-600 mx-auto" />
              <p className="text-slate-400 mt-4">No molecules found in this tab</p>
              <p className="text-slate-500 text-sm mt-2">
                Try adjusting your filters or search query
              </p>
            </div>
          )}
        </div>
      )}

      {activePageTab === 'dynamics' && (
        <div className="flex-1 overflow-hidden min-h-0 mt-4">
          <DynamicsPanel
            selectedMolId={selectedMolId}
            onSelectMolId={setSelectedMolId}
            molecules={molecules}
          />
        </div>
      )}

      <ScanDatabaseModal
        open={scanModalOpen}
        onClose={() => { setScanModalOpen(false); refetch() }}
      />
    </div>
  )
}

export default Molecules
