import { useState, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, AlertCircle, Play } from 'lucide-react'
import { useMolecules } from '../hooks/useMolecules'
import { useSubmitSingleMoleculeBatch } from '../hooks/useApiExperiments'
import { useNotification } from '../hooks/useNotification'
import { NotificationBanner, PageHeader } from './shared'
import ProtocolTimeline from './ProtocolTimeline'
import TemperatureSelectorHybrid from './shared/TemperatureSelectorHybrid'
import { ROUTE_KEYS, ROUTE_META } from '../navigation/routeMeta'
import { chipButtonClass as chipButtonClassFn } from '../lib/chipButton'
import { getTodaySeed } from '../lib/seed'
import { useSubmissionEIntraMethod } from '../hooks/useSubmissionEIntraMethod'
import {
  ELIGIBLE_SOURCES,
  SINGLE_MOL_SELECTED_STAGES,
  SINGLE_MOL_STAGE_CONFIG,
  inferSourceKey,
} from './single-molecule/shared'
import MoleculeChipGrid from './single-molecule/MoleculeChipGrid'
import {
  SUBMISSION_E_INTRA_METHOD_OPTIONS,
  getSubmissionEIntraMethodLabel,
  getSubmissionEIntraMethodProfile,
} from '../lib/eIntraMethod'

function SingleMoleculeScreen() {
  const [selectedMolId, setSelectedMolId] = useState(null)
  const [activeSourceTab, setActiveSourceTab] = useState('asphalt_binder')
  const [activeAgingTab, setActiveAgingTab] = useState('non_aging')
  const [temperature, setTemperature] = useState(293)
  const [seed, setSeed] = useState(getTodaySeed())
  const [forceRecompute, setForceRecompute] = useState(false)
  // precompute removed — artifact auto-generates on build

  const {
    defaultEIntraMethod,
    effectiveEIntraMethod,
    selectedEIntraMethod,
    setSelectedEIntraMethod,
  } = useSubmissionEIntraMethod()
  const { molecules, loading, error, refetch } = useMolecules({
    limit: 5000,
    eIntraMethod: effectiveEIntraMethod,
  })
  const submitMutation = useSubmitSingleMoleculeBatch()
  const { notification, notify, dismiss } = useNotification(8000)
  const methodProfile = getSubmissionEIntraMethodProfile(effectiveEIntraMethod)

  const chipButtonClass = (active, colorScheme = 'blue') =>
    chipButtonClassFn(active, { colorScheme })

  const eligibleMolecules = useMemo(
    () => molecules.filter((mol) => ELIGIBLE_SOURCES.has(inferSourceKey(mol))),
    [molecules],
  )
  const tabCounts = useMemo(() => {
    const counts = { asphalt_binder: 0, single_moles: 0, additives: 0 }
    eligibleMolecules.forEach((mol) => { counts[inferSourceKey(mol)] = (counts[inferSourceKey(mol)] || 0) + 1 })
    return counts
  }, [eligibleMolecules])
  const asphaltAgingCounts = useMemo(() => {
    const counts = { non_aging: 0, short_aging: 0, long_aging: 0 }
    eligibleMolecules.forEach((mol) => {
      if (inferSourceKey(mol) !== 'asphalt_binder') return
      counts[mol.aging_state || 'non_aging'] = (counts[mol.aging_state || 'non_aging'] || 0) + 1
    })
    return counts
  }, [eligibleMolecules])
  const filteredMolecules = useMemo(() => {
    let list = eligibleMolecules.filter((mol) => inferSourceKey(mol) === activeSourceTab)
    if (activeSourceTab === 'asphalt_binder') list = list.filter((mol) => mol.aging_state === activeAgingTab)
    return list
  }, [eligibleMolecules, activeSourceTab, activeAgingTab])

  const selectedMolecule = useMemo(
    () => filteredMolecules.find((mol) => mol.mol_id === selectedMolId) || null,
    [filteredMolecules, selectedMolId],
  )

  const handleSubmit = useCallback(async () => {
    if (!selectedMolId || !temperature) return
    // Fail-closed defense: block submit if molecule is null or not submittable
    // This guards against stale state / race conditions (e.g., molecule disappeared after refetch)
    if (!selectedMolecule || selectedMolecule.is_submittable === false) return
    dismiss()
    try {
      const payload = {
        selected_mol_id: selectedMolId,
        temperatures_k: [temperature],
        seed,
        force_recompute: forceRecompute,
        e_intra_method: effectiveEIntraMethod,
      }
      console.log('[SingleMolecule] submit payload:', payload)
      const result = await submitMutation.mutateAsync(payload)
      console.log('[SingleMolecule] submit response:', result)

      // Honest result reporting — check actual counts, not just no-throw
      const submitted = result?.submitted ?? 0
      const skipped = result?.skipped_existing ?? 0
      const failed = result?.failed ?? 0
      const firstFail = result?.items?.find((i) => i.status === 'failed')
      const errMsg = firstFail?.error || 'unknown'
      const errType = firstFail?.error_type ? ` [${firstFail.error_type}]` : ''

      if (submitted > 0) {
        const parts = [`${submitted} submitted`]
        if (skipped) parts.push(`${skipped} skipped`)
        if (failed) parts.push(`${failed} failed`)
        notify('success', parts.join(', '))
      } else if (failed > 0) {
        notify('error', `Submission failed${errType}: ${errMsg}`)
      } else if (skipped > 0) {
        notify('warning', `Skipped (${skipped}) — already exists`)
      } else {
        notify('warning', 'No submissions made')
      }
    } catch (err) {
      console.error('[SingleMolecule] submit error:', err)
      console.error('[SingleMolecule] error response:', err?.response)
      const detail = err?.response?.data?.detail
      const detailMsg = Array.isArray(detail)
        ? detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
        : (typeof detail === 'string' ? detail : null)
      notify('error', detailMsg || err?.message || 'Submission failed')
    }
  }, [selectedMolId, selectedMolecule, temperature, seed, forceRecompute, effectiveEIntraMethod, submitMutation, notify, dismiss])

  if (loading && molecules.length === 0) {
    return (<div className="flex items-center justify-center p-12"><Loader2 className="w-8 h-8 text-blue-400 animate-spin" /><span className="ml-3 text-slate-400">Loading molecules...</span></div>)
  }
  if (error) {
    return (<div className="card p-8 text-center"><AlertCircle className="w-12 h-12 text-red-400 mx-auto" /><p className="text-red-400 mt-4">{error}</p><button onClick={refetch} className="mt-4 px-4 py-2 bg-blue-500/20 text-blue-400 rounded hover:bg-blue-500/30">Retry</button></div>)
  }

  return (
    <div className="space-y-4 pb-6">
      <PageHeader routeKey={ROUTE_KEYS.SINGLE_JOB_SINGLE_MOLECULE} subtitle="Submit a single E_intra calculation" />
      <NotificationBanner notification={notification} onDismiss={dismiss} />

      <div className="card p-4 space-y-3">
        {/* Row 1: Left stack (Timeline + Summary + Selected) | Right (Molecule Selection) */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Left: stacked vertically */}
          <div className="space-y-2">
            {/* Protocol Timeline — compact, no flex-1 */}
            <div className="text-sm text-slate-300">
              <div className="text-sm font-semibold mb-1">Protocol Timeline</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
                <ProtocolTimeline selectedStages={SINGLE_MOL_SELECTED_STAGES} stageConfig={SINGLE_MOL_STAGE_CONFIG} legendPosition="inline" />
              </div>
            </div>
            {/* Protocol Summary */}
            <div className="text-sm text-slate-300 flex-1 flex flex-col">
              <div className="text-sm font-semibold mb-1">Protocol Summary</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1 space-y-2">
                {/* Stages */}
                <div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Stages</div>
                  <div className="grid grid-cols-3 gap-x-3 text-xs">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: '#94A3B8' }} />
                      <div>
                        <div className="text-slate-200">Minimize</div>
                        <div className="text-[10px] text-slate-500">1000 steps</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: '#F59E0B' }} />
                      <div>
                        <div className="text-slate-200">NVT</div>
                        <div className="text-[10px] text-slate-500">300 ps</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full shrink-0 bg-slate-700" />
                      <div>
                        <div className="text-slate-500 line-through">NPT</div>
                        <div className="text-[10px] text-slate-600">skipped</div>
                      </div>
                    </div>
                  </div>
                </div>
                {/* Simulation settings */}
                <div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Simulation</div>
                  <div className="grid grid-cols-3 gap-x-3 text-xs">
                    <div>
                      <div className="text-slate-500">Boundary</div>
                      <div className="text-slate-200 font-mono">{methodProfile.boundary}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Kspace</div>
                      <div className="text-slate-200">{methodProfile.kspace}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Pair style</div>
                      <div className="text-slate-200 font-mono text-[11px]">{methodProfile.pairStyle}</div>
                    </div>
                  </div>
                </div>
                {/* Study info */}
                <div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Study</div>
                  <div className="grid grid-cols-3 gap-x-3 text-xs">
                    <div>
                      <div className="text-slate-500">Method</div>
                      <div className="text-slate-200">{methodProfile.studyLabel}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Force field</div>
                      <div className="text-slate-200">bulk_ff_gaff2</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Mixing</div>
                      <div className="text-slate-200">geometric</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right: Molecule Selection — height matches left stack */}
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Molecule Selection</div>
            <MoleculeChipGrid
              filteredMolecules={filteredMolecules}
              selectedMolId={selectedMolId}
              onSelect={setSelectedMolId}
              activeSourceTab={activeSourceTab}
              onSourceTabChange={(key) => { setActiveSourceTab(key); setSelectedMolId(null) }}
              activeAgingTab={activeAgingTab}
              onAgingTabChange={(key) => { setActiveAgingTab(key); setSelectedMolId(null) }}
              tabCounts={tabCounts}
              asphaltAgingCounts={asphaltAgingCounts}
              chipButtonClass={chipButtonClass}
            />
          </div>
        </div>

        {/* Row 2: Temperature (single) + FF/Boundary + Seed + Options/Submit */}
        <div className="grid grid-cols-1 md:grid-cols-[1.7fr_0.9fr_0.8fr_1fr] gap-3 items-stretch">
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Temperature (K)</div>
            <TemperatureSelectorHybrid value={temperature} onChange={setTemperature} presetColumns={7} compact showTitle={false} />
          </div>
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Applied Profile</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
              <div
                className={chipButtonClass(
                  true,
                  selectedMolecule?.route === 'inorganic_profile'
                    ? 'amber'
                    : selectedMolecule?.route === 'ionic_profile'
                      ? 'rose'
                      : 'cyan',
                )}
                title={selectedMolecule?.ff_display_label || 'GAFF2'}
              >
                {selectedMolecule?.ff_display_label || 'GAFF2'}
              </div>
            </div>
            <div className="text-sm font-semibold mt-2 mb-1">Boundary</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
              <div className={chipButtonClass(true)}>{methodProfile.boundary}</div>
            </div>
          </div>
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Seed</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
              <input type="number" min={0} step={1} value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} className="input w-full h-7 py-0 text-xs" placeholder="YYYYMMDD" aria-label="Seed" />
            </div>
          </div>
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Options</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 mb-2">
              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input type="checkbox" checked={forceRecompute} onChange={(e) => setForceRecompute(e.target.checked)} className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500" />
                Force recompute
              </label>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 mb-2 space-y-1.5">
              <div className="text-[10px] text-slate-500">
                Default: {getSubmissionEIntraMethodLabel(defaultEIntraMethod)}
              </div>
              <select
                className="input w-full h-8 py-1 text-xs"
                value={selectedEIntraMethod}
                onChange={(e) => setSelectedEIntraMethod(e.target.value)}
                aria-label="E_intra Method Override"
              >
                {SUBMISSION_E_INTRA_METHOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <div className="text-[10px] text-slate-500">
                Submit: {getSubmissionEIntraMethodLabel(effectiveEIntraMethod)}
              </div>
            </div>
            {/* Blocked hint — fail-closed policy. Artifact management moved to
                /molecules canonical surface (v00.99.66). The ?mol_id=… deep
                link auto-selects the blocked molecule on arrival. */}
            {selectedMolecule && selectedMolecule.is_submittable === false && (
              <div className="text-[10px] text-amber-400/90 mb-1.5">
                <div>Selected molecule requires an artifact before submission.</div>
                <Link
                  to={`${ROUTE_META[ROUTE_KEYS.MOLECULES].path}?mol_id=${encodeURIComponent(selectedMolecule.mol_id)}`}
                  className="mt-1 inline-block text-blue-400 hover:text-blue-300 underline"
                >
                  Manage FF artifacts in Molecules catalog →
                </Link>
              </div>
            )}
            <button type="button" onClick={handleSubmit} disabled={!selectedMolId || !selectedMolecule || submitMutation.isPending || selectedMolecule.is_submittable === false}
              className="btn btn-primary py-2 px-4 text-sm font-medium w-full flex items-center justify-center gap-2 mt-auto">
              {submitMutation.isPending ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Submitting...</>
              ) : (<><Play className="w-4 h-4" /> Submit</>)}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SingleMoleculeScreen
