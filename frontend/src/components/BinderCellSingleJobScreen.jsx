import { useState, useEffect, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Play } from 'lucide-react'
import { NotificationBanner, PrecisionAnalysisPanel, AppliedForceFieldNote } from './shared'
import { useNotification } from '../hooks/useNotification'
import {
  submitMoleculeExperiment,
  previewMoleculeComposition,
} from '../api/client'
import { chipButtonClass as chipButtonClassFn } from '../lib/chipButton'
import MoleculePreview from './MoleculePreview'
import ProtocolStagesPanel from './ProtocolStagesPanel'
import CompositionCards from './CompositionCards'
import TemperatureSelectorHybrid from './shared/TemperatureSelectorHybrid'
import PageHeader from './shared/PageHeader'
import BinderSelectionRow from './binder-cell/BinderSelectionRow'
import BinderAdditivesPanel from './binder-cell/BinderAdditivesPanel'
import useProtocolStages from '../hooks/useProtocolStages'
import useAdditives from '../hooks/useAdditives'
import useBinderTypes from '../hooks/useBinderTypes'
import useMoleculeWeights from '../hooks/useMoleculeWeights'
import { useEInterRecommendation } from '../hooks/useApi'
import { getAdditiveDisplayLabel, getAdditiveDisplayName } from '../lib/additiveLabel'
import { getTodaySeed } from '../lib/seed'
import { ROUTE_KEYS, ROUTE_META } from '../navigation/routeMeta'
import { useSubmissionEIntraMethod } from '../hooks/useSubmissionEIntraMethod'
import { validateSingleJobForm, buildSingleJobPayload } from './binder-cell/submitHelpers'
import useBinderComposition from './binder-cell/useBinderComposition'
import { computeBinderWeightForSystem } from './binder-cell/binderWeight'
import {
  SUBMISSION_E_INTRA_METHOD_OPTIONS,
  getSubmissionEIntraMethodLabel,
} from '../lib/eIntraMethod'

const LAST_PROTOCOL_STORAGE_KEY = 'asphalt:last-binder-cell-single-job-protocol'

const ADDITIVE_SUMMARY_GRID = 'grid-cols-[minmax(0,1fr)_52px_64px_72px_52px]'
const BOUNDARY_OPTIONS = [
  { value: 'ppp', label: 'p p p' },
  { value: 'ppf', label: 'p p f' },
]

function BinderCellSingleJobScreen() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const { notification, notify, dismiss } = useNotification()

  // Binder type selection
  const [binderType, setBinderType] = useState('AAA1')
  const [structureSize, setStructureSize] = useState('X1')
  const [agingState, setAgingState] = useState('non_aging')

  // Additives
  const [selectedAdditives, setSelectedAdditives] = useState([])
  const { binderTypes } = useBinderTypes({ asObjects: true })
  const { additives: availableAdditives } = useAdditives()
  const { weightMap: moleculeWeightMap } = useMoleculeWeights()

  // Simulation parameters
  const [temperature, setTemperature] = useState(293)
  // GAFF2 is the only active organic track (ReaxFF submission is not used). When
  // an inorganic species is added, the FF is automatically combined based on the
  // route, and AppliedForceFieldNote only displays the applied result.
  const ffType = 'bulk_ff_gaff2'
  const [boundaryMode, setBoundaryMode] = useState('ppp')
  const [seed, setSeed] = useState(() => getTodaySeed())
  const [initialDensity, setInitialDensity] = useState(0.2)
  const {
    defaultEIntraMethod,
    effectiveEIntraMethod,
    selectedEIntraMethod,
    setSelectedEIntraMethod,
  } = useSubmissionEIntraMethod()

  const {
    selectedStages,
    stageConfig,
    stageDurations,
    loadingStages,
    computedRunTier,
    toggleStage,
    handleDurationChange,
    resetDurationToDefault,
    isDurationModified,
    buildStageOverrides,
    buildStageRequests,
    timelineStageConfig,
    viscosityTemps,
    addViscosityTemp,
    removeViscosityTemp,
    updateViscosityTemp,
    equilibrationParams,
    updateEquilibrationParam,
    buildEquilibrationSettings,
  } = useProtocolStages()

  // E_inter precision analysis (precise calculation of interface/component
  // interaction energy — same role as the batch job).
  // The backend policy determines the recommendation level (none/optional/
  // recommended/required) from workflow="binder_cell" + has_additive →
  // displays PrecisionAnalysisPanel, submits via interaction_analysis.
  const { data: eInterRecommendation } = useEInterRecommendation(
    {
      workflow: 'binder_cell',
      tier: computedRunTier || 'screening',
      has_additive: selectedAdditives.length > 0,
    },
    true,
  )
  const [interactionAnalysisEnabled, setInteractionAnalysisEnabled] = useState(false)

  // ff_assignment route of the selected additives → automatic display of the
  // applied FF stack (not a selection). When an inorganic species
  // (inorganic_profile, e.g. SiO2) is included, INTERFACE FF is combined automatically.
  const additiveRoutes = useMemo(
    () =>
      selectedAdditives
        .map((a) => availableAdditives.find((av) => av.mol_id === a.mol_id)?.route)
        .filter(Boolean),
    [selectedAdditives, availableAdditives],
  )

  const interactionAnalysisConfig = useMemo(() => {
    const level = eInterRecommendation?.level
    if (!level || level === 'none') return null
    // For required level, force-enable; otherwise follow the user toggle (same rule as the batch job)
    const enabled = level === 'required' || interactionAnalysisEnabled
    if (!enabled) return null
    const rawMetrics = eInterRecommendation?.affected_metrics
    const metrics = rawMetrics?.length ? rawMetrics : ['e_inter_total']
    return { enabled: true, metrics, auto_trigger_rerun: true }
  }, [eInterRecommendation, interactionAnalysisEnabled])

  // Custom mode
  const isCustomMode = binderType === 'custom'

  // Composition loading via shared hook (non-custom mode)
  const {
    moleculeCounts: hookMoleculeCounts,
    totalMolecules: hookTotalMolecules,
    estimatedAtoms: hookEstimatedAtoms,
    loading: loadingComposition,
    setMoleculeCounts: hookSetMoleculeCounts,
    setTotalMolecules: hookSetTotalMolecules,
    setEstimatedAtoms: hookSetEstimatedAtoms,
    setSaraFractions: hookSetSaraFractions,
  } = useBinderComposition({
    binderType,
    structureSize,
    agingState,
    enabled: !isCustomMode,
  })

  // Alias for unified access (hook manages state for both custom/non-custom)
  const moleculeCounts = hookMoleculeCounts
  const setMoleculeCounts = hookSetMoleculeCounts
  const totalMolecules = hookTotalMolecules
  const setTotalMolecules = hookSetTotalMolecules
  const estimatedAtoms = hookEstimatedAtoms
  const setEstimatedAtoms = hookSetEstimatedAtoms
  const setSaraFractions = hookSetSaraFractions

  // FF eligibility from preview
  const [ffBlockedItems, setFfBlockedItems] = useState([])
  // Warnings remain in the API payload for compatibility, but submit UI only
  // surfaces fail-closed blockers.
  const [, setFfWarningItems] = useState([])
  // Custom mode preview has its own loading state, combined with hook loading
  const [customPreviewLoading, setCustomPreviewLoading] = useState(false)
  const loadingCompositionCombined = loadingComposition || customPreviewLoading

  const additiveCatalog = useMemo(() => {
    return availableAdditives.reduce((acc, item) => {
      if (item?.mol_id) acc[item.mol_id] = item
      return acc
    }, {})
  }, [availableAdditives])

  const binderWeight = useMemo(() => {
    return computeBinderWeightForSystem(moleculeCounts, agingState, moleculeWeightMap)
  }, [moleculeCounts, moleculeWeightMap, agingState])

  const additiveSummary = useMemo(() => {
    const rows = selectedAdditives.map((selected) => {
      const item = additiveCatalog[selected.mol_id] || {}
      const molecularWeight = Number(item.molecular_weight || selected.molecular_weight || 0)
      const moleculeCount = Math.max(0, Number(selected.count || 0))
      const weight = moleculeCount * molecularWeight
      return {
        molId: selected.mol_id,
        name: getAdditiveDisplayLabel(selected.mol_id, additiveCatalog),
        molecularWeight,
        moleculeCount,
        weight,
      }
    })

    const totalAdditiveWeight = rows.reduce((sum, row) => sum + row.weight, 0)
    const denominator = binderWeight + totalAdditiveWeight
    const rowsWithRatio = rows.map((row) => ({
      ...row,
      ratioPct: denominator > 0 ? (row.weight / denominator) * 100 : 0,
    }))

    return {
      rows: rowsWithRatio,
      totalAdditiveWeight,
      totalConcentrationPct: denominator > 0 ? (totalAdditiveWeight / denominator) * 100 : 0,
      binderPct: denominator > 0 ? (binderWeight / denominator) * 100 : 0,
      binderWeight,
    }
  }, [selectedAdditives, additiveCatalog, binderWeight])

  const compositionCards = useMemo(() => {
    const binderCards = moleculeCounts.map((mol, index) => ({
      key: `mol:${mol.mol_id}`,
      molId: mol.mol_id,
      title: mol.mol_id,
      saraType: mol.sara_type,
      count: mol.count,
      atomCount: mol.atom_count || 50,
      kind: 'binder',
      index,
    }))
    const additiveCards = selectedAdditives.map((add) => {
      const info = additiveCatalog[add.mol_id] || {}
      const subtitle = info.name && info.name !== add.mol_id
        ? add.mol_id
        : (info.category || 'Additive')
      return {
        key: `add:${add.mol_id}`,
        molId: add.mol_id,
        title: getAdditiveDisplayName(add.mol_id, additiveCatalog),
        subtitle,
        count: add.count,
        atomCount: add.atom_count || info.atom_count || 50,
        kind: 'additive',
      }
    })
    return [...binderCards, ...additiveCards]
  }, [moleculeCounts, selectedAdditives, additiveCatalog])

  // UI state
  const [previewMolecule, setPreviewMolecule] = useState(null)

  // Optional property calculations (legacy, kept for viscosity temps)

  useEffect(() => {
    if (isCustomMode) return
    const names = binderTypes.map((bt) => bt.name)
    if (binderTypes.length > 0 && !names.includes(binderType)) {
      setBinderType(binderTypes[0].name)
    }
  }, [binderTypes, binderType, isCustomMode])

  useEffect(() => {
    if (isCustomMode) {
      setSaraFractions({})
    }
  }, [isCustomMode, setSaraFractions])

  // FF eligibility preview — runs in both custom and normal mode
  // whenever moleculeCounts or selectedAdditives change.
  useEffect(() => {
    let active = true

    if (moleculeCounts.length === 0) {
      setFfBlockedItems([])
      setFfWarningItems([])
      if (isCustomMode) setSaraFractions({})
      return undefined
    }

    const payload = {
      binder_type: binderType,
      structure_size: structureSize,
      aging_state: agingState,
      temperature_K: temperature,
      molecule_counts: moleculeCounts.map(m => ({ mol_id: m.mol_id, count: m.count })),
      additives: selectedAdditives.length > 0
        ? selectedAdditives.map(a => ({ mol_id: a.mol_id, count: a.count }))
        : null,
    }

    const timeout = setTimeout(async () => {
      setCustomPreviewLoading(true)
      try {
        const response = await previewMoleculeComposition(payload)
        if (!active) return
        // Custom mode: update sara from preview; normal mode: hook handles sara
        if (isCustomMode) setSaraFractions(response.sara_fractions || {})
        setFfBlockedItems(response.ff_blocked_items || [])
        setFfWarningItems(response.ff_warning_items || [])
      } catch (err) {
        if (!active) return
        console.error('Failed to preview composition:', err)
        // Keep last known ffBlockedItems/ffWarningItems on transient failure
      } finally {
        if (active) setCustomPreviewLoading(false)
      }
    }, 300)

    return () => {
      active = false
      clearTimeout(timeout)
      setCustomPreviewLoading(false)
    }
  }, [
    isCustomMode,
    binderType,
    structureSize,
    agingState,
    temperature,
    moleculeCounts,
    selectedAdditives,
    setSaraFractions,
  ])

  // Handle molecule count change (custom mode)
  const handleMoleculeCountChange = (index, newCount) => {
    const updated = [...moleculeCounts]
    updated[index] = { ...updated[index], count: Math.max(0, newCount) }
    setMoleculeCounts(updated)

    // Recalculate totals using API-provided atom_count (SSOT)
    const total = updated.reduce((sum, m) => sum + m.count, 0)
    setTotalMolecules(total)

    // Use atom_count from API response (SSOT) with fallback
    const atoms = updated.reduce((sum, m) => sum + m.count * (m.atom_count || 50), 0)
    setEstimatedAtoms(atoms)
  }

  // Handle additive toggle
  const handleAdditiveToggle = (additive) => {
    if (additive.mol_id === '__none__') {
      setSelectedAdditives([])
      return
    }
    const exists = selectedAdditives.find(a => a.mol_id === additive.mol_id)
    if (exists) {
      setSelectedAdditives(selectedAdditives.filter(a => a.mol_id !== additive.mol_id))
    } else {
      const defaultCount = additive.default_counts?.[structureSize] || 2
      // Include atom_count from API for accurate atom estimation
      setSelectedAdditives([...selectedAdditives, {
        mol_id: additive.mol_id,
        count: defaultCount,
        atom_count: additive.atom_count || 50,
        molecular_weight: additive.molecular_weight || 0,
        name: additive.name
      }])
    }
  }

  // Handle additive count change
  const handleAdditiveCountChange = (molId, newCount) => {
    setSelectedAdditives(selectedAdditives.map(a =>
      a.mol_id === molId ? { ...a, count: Math.max(0, newCount) } : a
    ))
  }

  // Submit experiment
  const handleSubmit = async (e) => {
    e.preventDefault()

    const validationError = validateSingleJobForm({ moleculeCounts, totalMolecules, seed })
    if (validationError) {
      notify('error',validationError)
      return
    }

    setLoading(true)
    dismiss()

    try {
      const payload = buildSingleJobPayload({
        binderType,
        structureSize,
        agingState,
        moleculeCounts,
        selectedAdditives,
        temperature,
        boundaryMode,
        seed,
        computedRunTier,
        ffType,
        initialDensity,
        selectedStages,
        viscosityTemps,
        buildStageOverrides,
        buildStageRequests,
        buildEquilibrationSettings,
        eIntraMethod: effectiveEIntraMethod,
        interactionAnalysis: interactionAnalysisConfig,
      })

      await submitMoleculeExperiment(payload)

      // Navigate to dashboard
      navigate('/')
    } catch (err) {
      notify('error',err.response?.data?.detail || err.message)
    } finally {
      setLoading(false)
    }
  }

  // Enter custom mode
  const enterCustomMode = () => {
    setBinderType('custom')
  }

  useEffect(() => {
    try {
      const payload = {
        selectedStages,
        stageConfig: timelineStageConfig,
        temperature,
        ff_type: ffType,
        boundary_mode: boundaryMode,
        seed: seed === '' ? null : Number(seed),
        e_intra_method: effectiveEIntraMethod,
        savedAt: new Date().toISOString(),
      }
      localStorage.setItem(LAST_PROTOCOL_STORAGE_KEY, JSON.stringify(payload))
    } catch (err) {
      console.error('Failed to persist protocol snapshot:', err)
    }
  }, [selectedStages, timelineStageConfig, temperature, ffType, boundaryMode, seed, effectiveEIntraMethod])

  // chipButtonClass imported from lib/chipButton (fontWeight='medium' for this page)
  const chipButtonClass = (active, colorScheme = 'blue') =>
    chipButtonClassFn(active, { colorScheme })

  // Total atoms including additives
  const totalAtoms = estimatedAtoms + selectedAdditives.reduce((sum, a) => sum + a.count * (a.atom_count || 50), 0)
  const handleTemperatureChange = (nextTemp) => {
    setTemperature(nextTemp)
  }

  return (
    <div className="space-y-4">
      <PageHeader
        routeKey={ROUTE_KEYS.SINGLE_JOB_BINDER_CELL}
        subtitle="Configure a single Binder Cell simulation."
      />

      <NotificationBanner notification={notification} onDismiss={dismiss} />

      <form onSubmit={handleSubmit}>
        <div className="card p-4 space-y-3">
          <BinderSelectionRow
            selectedStages={selectedStages}
            timelineStageConfig={timelineStageConfig}
            binderTypes={binderTypes}
            binderType={binderType}
            setBinderType={setBinderType}
            enterCustomMode={enterCustomMode}
            isCustomMode={isCustomMode}
            structureSize={structureSize}
            setStructureSize={setStructureSize}
            agingState={agingState}
            setAgingState={setAgingState}
            chipButtonClass={chipButtonClass}
          />

          {/* Row 2: Protocol Stages (2) + Composition (2) */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-stretch">
            <ProtocolStagesPanel
              stageConfig={stageConfig}
              stageDurations={stageDurations}
              selectedStages={selectedStages}
              loading={loadingStages}
              onToggleStage={toggleStage}
              onDurationChange={handleDurationChange}
              onResetDuration={resetDurationToDefault}
              isDurationModified={isDurationModified}
              viscosityTemps={viscosityTemps}
              onViscosityTempChange={updateViscosityTemp}
              onAddViscosityTemp={addViscosityTemp}
              onRemoveViscosityTemp={removeViscosityTemp}
              equilibrationParams={equilibrationParams}
              onEquilibrationParamChange={updateEquilibrationParam}
            />
          <div className="text-sm text-slate-300 md:col-span-2 flex flex-col">
              <div className="text-sm font-semibold mb-1 flex items-center gap-2">
                Composition
                {loadingCompositionCombined && (
                  <div className="w-3 h-3 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
                )}
                <span className="text-xs text-slate-400 font-normal">
                  {totalMolecules + selectedAdditives.reduce((sum, a) => sum + a.count, 0)} mol / ~{(totalAtoms / 1000).toFixed(1)}k atoms
                </span>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1 flex flex-col min-h-0">
                {/* Molecule Cards */}
                <div className="flex-1 min-h-0 overflow-y-auto">
                  <CompositionCards
                    cards={compositionCards}
                    editable={isCustomMode}
                    onCountChange={handleMoleculeCountChange}
                    onPreview={(card) => setPreviewMolecule({ mol_id: card.molId, name: card.title })}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Row 3: Temperature + Additives + Force Field(+Boundary/Seed) */}
          <div className="grid grid-cols-1 md:grid-cols-[1.7fr_0.75fr_0.75fr_0.75fr_0.75fr] gap-3 items-stretch">
            <div className="text-sm text-slate-300 flex flex-col">
              <div className="text-sm font-semibold mb-1">Temperature (K)</div>
              <TemperatureSelectorHybrid
                value={temperature}
                onChange={handleTemperatureChange}
                presetColumns={7}
                compact
                showTitle={false}
              />
            </div>
            <div className="md:col-span-2">
              <BinderAdditivesPanel
                availableAdditives={availableAdditives}
                selectedAdditives={selectedAdditives}
                handleAdditiveToggle={handleAdditiveToggle}
                chipButtonClass={chipButtonClass}
                additiveSummary={additiveSummary}
                handleAdditiveCountChange={handleAdditiveCountChange}
                additiveSummaryGrid={ADDITIVE_SUMMARY_GRID}
              />
            </div>
            <div className="text-sm text-slate-300 flex flex-col">
              <div className="text-sm font-semibold mb-1">Force Field</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
                <AppliedForceFieldNote ffType={ffType} additiveRoutes={additiveRoutes} />
              </div>

              <div className="text-sm font-semibold mt-2 mb-1">Boundary</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
                <div className="flex flex-nowrap gap-1 overflow-x-auto">
                  {BOUNDARY_OPTIONS.map((boundaryOption) => (
                    <button
                      key={boundaryOption.value}
                      type="button"
                      onClick={() => setBoundaryMode(boundaryOption.value)}
                      className={chipButtonClass(boundaryMode === boundaryOption.value, 'blue')}
                    >
                      {boundaryOption.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="text-sm font-semibold mt-2 mb-1">Initial Density (g/cm3)</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
                <input
                  type="number"
                  min={0.1}
                  max={2.0}
                  step={0.1}
                  value={initialDensity}
                  onChange={(e) => setInitialDensity(Math.max(0.1, Math.min(2.0, Number(e.target.value) || 0.2)))}
                  className="input w-full h-7 py-0 text-xs"
                  aria-label="Initial Density"
                />
                <p className="text-[10px] text-slate-500 mt-1">Packmol packing density</p>
              </div>

              {eInterRecommendation && (
                <div className="mt-2">
                  <PrecisionAnalysisPanel
                    recommendation={eInterRecommendation}
                    onChange={setInteractionAnalysisEnabled}
                    compact
                  />
                </div>
              )}

            </div>
            <div className="text-sm text-slate-300 flex flex-col">
              <div className="text-sm font-semibold mb-1">Seed</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 mb-2">
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={seed}
                  onChange={(event) => setSeed(event.target.value)}
                  className="input w-full h-7 py-0 text-xs"
                  placeholder="YYYYMMDD"
                  aria-label="Seed"
                />
              </div>
              <div className="text-sm font-semibold mb-1">E_intra Method</div>
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
              {/* FF blocked items warning */}
              {ffBlockedItems.length > 0 && (
                <div className="text-[10px] text-amber-400/90 mb-2 px-1 space-y-0.5">
                  <div>
                    {ffBlockedItems.length} species require FF artifacts before submission.
                  </div>
                  <Link
                    to={`${ROUTE_META[ROUTE_KEYS.MOLECULES].path}?mol_id=${encodeURIComponent(ffBlockedItems[0]?.item_id || '')}`}
                    className="inline-block text-blue-400 hover:text-blue-300 underline"
                  >
                    Manage FF artifacts in Molecules catalog →
                  </Link>
                </div>
              )}
              <button
                type="submit"
                disabled={loading || totalMolecules === 0 || ffBlockedItems.length > 0}
                className="btn btn-primary py-2 px-4 text-sm font-medium w-full flex items-center justify-center gap-2 mt-5"
              >
                {loading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Submitting...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Submit
                  </>
                )}
              </button>
            </div>
          </div>

        </div>
      </form>

      {/* Molecule Preview Modal */}
      {previewMolecule && (
        <MoleculePreview
          molId={previewMolecule.mol_id}
          molName={previewMolecule.name || previewMolecule.mol_id}
          onClose={() => setPreviewMolecule(null)}
        />
      )}
    </div>
  )
}

export default BinderCellSingleJobScreen
