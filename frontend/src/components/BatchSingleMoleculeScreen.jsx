import { useState, useMemo, useEffect, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Loader2, AlertCircle, Play } from 'lucide-react'
import { useMolecules } from '../hooks/useMolecules'
import { useExperimentDefaults, useSubmitSingleMoleculeBatch } from '../hooks/useApiExperiments'
import { useNotification } from '../hooks/useNotification'
import { NotificationBanner, PageHeader } from './shared'
import ProtocolTimeline from './ProtocolTimeline'
import { ROUTE_KEYS, ROUTE_META } from '../navigation/routeMeta'
import { TEMPERATURE_PRESET_OPTIONS } from '../lib/temperature'
import { chipButtonClass as chipButtonClassFn } from '../lib/chipButton'
import { getTodaySeed } from '../lib/seed'
import { FALLBACK_TEMPERATURES_K } from './batch-binder-cell/config'
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

function BatchSingleMoleculeScreen() {
  const navigate = useNavigate()

  // State — multi-molecule + multi-temperature batch
  const [selectedMolIds, setSelectedMolIds] = useState([])
  const [activeSourceTab, setActiveSourceTab] = useState('asphalt_binder')
  const [activeAgingTab, setActiveAgingTab] = useState('non_aging')
  const [selectedTemperatures, setSelectedTemperatures] = useState(() => [...FALLBACK_TEMPERATURES_K])
  const [seed, setSeed] = useState(getTodaySeed())
  const [forceRecompute, setForceRecompute] = useState(false)
  const [defaultsHydrated, setDefaultsHydrated] = useState(false)
  const [temperaturesTouched, setTemperaturesTouched] = useState(false)
  const {
    defaultEIntraMethod,
    effectiveEIntraMethod,
    selectedEIntraMethod,
    setSelectedEIntraMethod,
  } = useSubmissionEIntraMethod()
  // Hooks
  const { molecules, loading, error, refetch } = useMolecules({
    limit: 5000,
    eIntraMethod: effectiveEIntraMethod,
  })
  const { data: expDefaults } = useExperimentDefaults()
  const submitMutation = useSubmitSingleMoleculeBatch()
  const { notification, notify, dismiss } = useNotification(8000)
  const methodProfile = getSubmissionEIntraMethodProfile(effectiveEIntraMethod)

  // precompute removed — artifact auto-generates on build

  // Hydrate default temperatures once — skip if user already edited
  useEffect(() => {
    if (expDefaults?.temperatures_k && !defaultsHydrated && !temperaturesTouched) {
      setSelectedTemperatures(expDefaults.temperatures_k)
      setDefaultsHydrated(true)
    }
  }, [expDefaults, defaultsHydrated, temperaturesTouched])

  const temperatureOptions = useMemo(
    () => expDefaults?.available_temperature_options_k || TEMPERATURE_PRESET_OPTIONS,
    [expDefaults],
  )

  const chipButtonClass = (active, colorScheme = 'blue') =>
    chipButtonClassFn(active, { colorScheme })

  // Molecule filtering
  const eligibleMolecules = useMemo(
    () => molecules.filter((mol) => ELIGIBLE_SOURCES.has(inferSourceKey(mol))),
    [molecules],
  )

  // Map for O(1) lookup — shared by selectedMolecules and ffSummary
  const moleculeMap = useMemo(() => {
    const map = new Map()
    eligibleMolecules.forEach((mol) => map.set(mol.mol_id, mol))
    return map
  }, [eligibleMolecules])

  // Derive selected entries from the full eligible set (not just filteredMolecules)
  // This ensures hidden-tab selections are still tracked for submit gating
  // NOTE: Do NOT use filter(Boolean) — keep null entries for fail-closed semantics
  const selectedEntries = useMemo(
    () => selectedMolIds.map((id) => ({ id, mol: moleculeMap.get(id) ?? null })),
    [selectedMolIds, moleculeMap],
  )

  // Check if any selected molecule is blocked (fail-closed gating)
  // blocked if: mol == null (disappeared) OR mol.is_submittable === false
  const blockedSelection = useMemo(() => {
    const blocked = selectedEntries.filter(
      ({ mol }) => mol == null || mol.is_submittable === false,
    )
    const allOrganic =
      blocked.length > 0 &&
      blocked.every(({ mol }) => mol?.route === 'organic_curated_artifact')
    // v00.99.66: first blocked mol_id is used to deep-link /molecules so the
    // operator doesn't have to search for it. `id` is the selected key even
    // if the mol itself disappeared from the catalog — safer than `mol?.mol_id`.
    const firstBlockedId = blocked[0]?.id ?? null
    return {
      count: blocked.length,
      hasBlocked: blocked.length > 0,
      allOrganic,
      firstBlockedId,
    }
  }, [selectedEntries])

  const tabCounts = useMemo(() => {
    const counts = { asphalt_binder: 0, single_moles: 0, additives: 0 }
    eligibleMolecules.forEach((mol) => {
      const src = inferSourceKey(mol)
      counts[src] = (counts[src] || 0) + 1
    })
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
    if (activeSourceTab === 'asphalt_binder') {
      list = list.filter((mol) => mol.aging_state === activeAgingTab)
    }
    return list
  }, [eligibleMolecules, activeSourceTab, activeAgingTab])

  // Toggle molecule selection
  const toggleMolecule = useCallback((molId) => {
    setSelectedMolIds((prev) =>
      prev.includes(molId) ? prev.filter((id) => id !== molId) : [...prev, molId],
    )
  }, [])

  // v00.99.66: FF route family summary kept for the Applied Profile chip
  // (mixed-route selections must be obvious before submit). Per-artifact
  // validation detail (bond/angle/dihedral counts) lives on /molecules.
  const ffSummary = useMemo(() => {
    let curated = 0
    let iface = 0
    let ionic = 0
    let legacy = 0
    selectedEntries.forEach(({ mol }) => {
      if (!mol) return
      const route =
        mol.route || (mol.ff_hint === 'interface_profile' ? 'inorganic_profile' : 'organic_rdkit_legacy')
      if (route === 'inorganic_profile') iface += 1
      else if (route === 'ionic_profile') ionic += 1
      else if (route === 'organic_curated_artifact') curated += 1
      else legacy += 1
    })
    return { curated, iface, ionic, legacy }
  }, [selectedEntries])

  // Toggle temperature
  const toggleTemperature = useCallback((temp) => {
    setTemperaturesTouched(true)
    setSelectedTemperatures((prev) =>
      prev.includes(temp) ? prev.filter((t) => t !== temp) : [...prev, temp].sort((a, b) => a - b),
    )
  }, [])

  // Submit all selected molecules → navigate to Dashboard only if all succeeded
  const handleSubmit = useCallback(async () => {
    if (selectedMolIds.length === 0 || selectedTemperatures.length === 0) return
    // Fail-closed defense: block submit if any selected molecule is not submittable
    // This guards against stale state / race conditions
    if (blockedSelection.hasBlocked) return
    dismiss()

    let totalSubmitted = 0
    let totalSkipped = 0
    let totalFailed = 0
    const errors = []

    try {
      for (const molId of selectedMolIds) {
        const payload = {
          selected_mol_id: molId,
          temperatures_k: selectedTemperatures,
          seed,
          force_recompute: forceRecompute,
          e_intra_method: effectiveEIntraMethod,
        }
        console.log('[BatchSingleMolecule] submit payload:', payload)
        const result = await submitMutation.mutateAsync(payload)
        console.log('[BatchSingleMolecule] submit response:', result)

        totalSubmitted += result?.submitted ?? 0
        totalSkipped += result?.skipped_existing ?? 0
        totalFailed += result?.failed ?? 0
        const firstFail = result?.items?.find((i) => i.status === 'failed')
        if (firstFail) {
          const errType = firstFail.error_type ? `[${firstFail.error_type}] ` : ''
          errors.push(`${molId}: ${errType}${firstFail.error}`)
        }
      }

      if (totalSubmitted > 0 && totalFailed === 0) {
        navigate('/')
      } else if (totalSubmitted > 0) {
        notify(
          'warning',
          `${totalSubmitted} submitted, ${totalSkipped} skipped, ${totalFailed} failed — ${errors[0] || ''}`,
        )
      } else if (totalFailed > 0) {
        notify('error', `All failed (${totalFailed}): ${errors[0] || 'unknown'}`)
      } else {
        notify('warning', `${totalSkipped} skipped — nothing new submitted`)
      }
    } catch (err) {
      console.error('[BatchSingleMolecule] submit error:', err)
      console.error('[BatchSingleMolecule] error response:', err?.response)
      const detail = err?.response?.data?.detail
      const detailMsg = Array.isArray(detail)
        ? detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
        : (typeof detail === 'string' ? detail : null)
      notify('error', detailMsg || err?.message || 'Submission failed')
    }
  }, [selectedMolIds, selectedTemperatures, seed, forceRecompute, effectiveEIntraMethod, submitMutation, notify, dismiss, navigate, blockedSelection.hasBlocked])

  if (loading && molecules.length === 0) {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading molecules...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card p-8 text-center">
        <AlertCircle className="w-12 h-12 text-red-400 mx-auto" />
        <p className="text-red-400 mt-4">{error}</p>
        <button onClick={refetch} className="mt-4 px-4 py-2 bg-blue-500/20 text-blue-400 rounded hover:bg-blue-500/30">Retry</button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <PageHeader routeKey={ROUTE_KEYS.BATCH_JOB_SINGLE_MOLECULE} subtitle="Submit batch E_intra calculations across multiple temperatures" />
      <NotificationBanner notification={notification} onDismiss={dismiss} />

      <div className="card p-4 space-y-3">
        {/* Row 1: Left stack (Timeline + Summary + Selected) | Right (Molecule Selection) */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Left: stacked vertically */}
          <div className="space-y-2">
            <div className="text-sm text-slate-300">
              <div className="text-sm font-semibold mb-1">Protocol Timeline</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
                <ProtocolTimeline selectedStages={SINGLE_MOL_SELECTED_STAGES} stageConfig={SINGLE_MOL_STAGE_CONFIG} legendPosition="inline" />
              </div>
            </div>
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
              multi
              selectedMolIds={selectedMolIds}
              onToggle={toggleMolecule}
              activeSourceTab={activeSourceTab}
              onSourceTabChange={(key) => { setActiveSourceTab(key) }}
              activeAgingTab={activeAgingTab}
              onAgingTabChange={(key) => { setActiveAgingTab(key) }}
              tabCounts={tabCounts}
              asphaltAgingCounts={asphaltAgingCounts}
              chipButtonClass={chipButtonClass}
            />
          </div>
        </div>

        {/* Row 3: Temperature (multi) + FF/Boundary + Seed + Options/Submit */}
        <div className="grid grid-cols-1 md:grid-cols-[1.7fr_0.9fr_0.8fr_1fr] gap-3 items-stretch">
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="flex items-center justify-between mb-1">
              <div className="text-sm font-semibold">Temperature (K)</div>
              <span className="text-[10px] text-slate-500">{selectedTemperatures.length} selected</span>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1">
              <div className="grid grid-cols-5 gap-1.5">
                {temperatureOptions.map((temp) => (
                  <button key={temp} type="button" onClick={() => toggleTemperature(temp)} className={chipButtonClass(selectedTemperatures.includes(temp))} aria-pressed={selectedTemperatures.includes(temp)}>
                    {temp}K
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Applied Profile</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
              {selectedMolIds.length === 0 ? (
                <div className="text-[10px] text-slate-500">Select molecules</div>
              ) : (
                <div className="space-y-1">
                  {ffSummary.legacy > 0 && (
                    <div className={chipButtonClass(true, 'cyan')}>Legacy RDKit ({ffSummary.legacy})</div>
                  )}
                  {ffSummary.curated > 0 && (
                    <div className={chipButtonClass(true, 'emerald')}>Curated Artifact ({ffSummary.curated})</div>
                  )}
                  {ffSummary.iface > 0 && (
                    <div className={chipButtonClass(true, 'amber')}>INTERFACE ({ffSummary.iface})</div>
                  )}
                  {ffSummary.ionic > 0 && (
                    <div className={chipButtonClass(true, 'rose')}>Ionic ({ffSummary.ionic})</div>
                  )}
                </div>
              )}
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
            {/* Inline hint for blocked selection — fail-closed policy
                (v00.99.29). Artifact management moved to /molecules canonical
                surface (v00.99.66). */}
            {blockedSelection.hasBlocked && (
              <div className="text-[10px] text-amber-400/90 mt-1.5 mb-1">
                <div>
                  {blockedSelection.allOrganic
                    ? `${blockedSelection.count} selected molecule${blockedSelection.count > 1 ? 's' : ''} require${blockedSelection.count === 1 ? 's' : ''} artifacts before submission.`
                    : `${blockedSelection.count} selected molecule${blockedSelection.count > 1 ? 's are' : ' is'} currently not submittable.`}
                </div>
                <Link
                  to={
                    blockedSelection.firstBlockedId
                      ? `${ROUTE_META[ROUTE_KEYS.MOLECULES].path}?mol_id=${encodeURIComponent(blockedSelection.firstBlockedId)}`
                      : ROUTE_META[ROUTE_KEYS.MOLECULES].path
                  }
                  className="mt-1 inline-block text-blue-400 hover:text-blue-300 underline"
                >
                  Manage FF artifacts in Molecules catalog →
                </Link>
              </div>
            )}
            <button type="button" onClick={handleSubmit} disabled={selectedMolIds.length === 0 || selectedTemperatures.length === 0 || submitMutation.isPending || blockedSelection.hasBlocked}
              className="btn btn-primary py-2 px-4 text-sm font-medium w-full flex items-center justify-center gap-2 mt-auto">
              {submitMutation.isPending ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Submitting...</>
              ) : (
                <><Play className="w-4 h-4" /> Submit</>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default BatchSingleMoleculeScreen
