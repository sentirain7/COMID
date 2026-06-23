import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { getBinderComposition } from '../api/client'
import { chipButtonClass as chipButtonClassFn } from '../lib/chipButton'
import { useCreateBatchJobBinderCell, useValidateBatchJobBinderCell, useEInterRecommendation } from '../hooks/useApi'
import useProtocolStages from '../hooks/useProtocolStages'
import ProtocolTimeline from './ProtocolTimeline'
import ProtocolStagesPanel from './ProtocolStagesPanel'
import MoleculePreview from './MoleculePreview'
import PageHeader from './shared/PageHeader'
import BatchJobBinderCellAxisSelectionPanel from './batch-binder-cell/BatchJobBinderCellAxisSelectionPanel'
import BatchJobBinderCellAdditivesPanel from './batch-binder-cell/BatchJobBinderCellAdditivesPanel'
import BatchJobBinderCellCompositionPanel from './batch-binder-cell/BatchJobBinderCellCompositionPanel'
import { BatchJobTemperaturePanel, BatchJobFFDensityPanel, BatchJobSeedCachePanel } from './batch-binder-cell/BatchJobBinderCellExecutionSettingsPanel'
import BatchJobBinderCellResponsePanel from './batch-binder-cell/BatchJobBinderCellResponsePanel'
import BatchJobBinderCellScenarioPreviewPanel from './batch-binder-cell/BatchJobBinderCellScenarioPreviewPanel'
import BatchJobBinderCellSubmissionPanel from './batch-binder-cell/BatchJobBinderCellSubmissionPanel'
import useAdditives from '../hooks/useAdditives'
import useBinderTypes from '../hooks/useBinderTypes'
import useMoleculeWeights from '../hooks/useMoleculeWeights'
import { AGING_STATE_OPTIONS, FALLBACK_BINDER_TYPE_NAMES, STRUCTURE_SIZE_OPTIONS } from '../lib/constants'
import { useExperimentDefaults } from '../hooks/useApiExperiments'
import { TEMPERATURE_PRESET_OPTIONS } from '../lib/temperature'
import { ROUTE_KEYS } from '../navigation/routeMeta'
import {
  ADDITIVE_SUMMARY_GRID,
  AGING_CODE,
  BINDER_CODE,
  defaultForm,
  SIMILAR_EXISTING_ACTION_OPTIONS,
} from './batch-binder-cell/config'
import { buildRequestPayload } from './batch-binder-cell/payloadBuilder'
import { computeAdditiveSummary, computeCompositionCards, computePreviewTotals } from './batch-binder-cell/computations'
import { computeBinderWeightForSystem } from './binder-cell/binderWeight'
import useBinderComposition from './binder-cell/useBinderComposition'
import {
  SUBMISSION_E_INTRA_METHOD_OPTIONS,
  getSubmissionEIntraMethodLabel,
} from '../lib/eIntraMethod'
import { useSubmissionEIntraMethod } from '../hooks/useSubmissionEIntraMethod'

function BatchJobBinderCellPage() {
  const [form, setForm] = useState(defaultForm)
  const { data: expDefaults } = useExperimentDefaults()
  const {
    defaultEIntraMethod,
    effectiveEIntraMethod,
    selectedEIntraMethod,
    setSelectedEIntraMethod,
  } = useSubmissionEIntraMethod()
  const effectiveEIntraMethodLabel = getSubmissionEIntraMethodLabel(effectiveEIntraMethod)

  // Hydrate form with API defaults once loaded (temperature SSOT)
  useEffect(() => {
    if (expDefaults) {
      setForm((prev) => ({
        ...prev,
        temperatures_k: expDefaults.temperatures_k || prev.temperatures_k,
        temperature_priority: expDefaults.temperature_priority || prev.temperature_priority,
      }))
    }
  }, [expDefaults])

  const { binderTypes: binderTypeOptions } = useBinderTypes()
  const { additives, catalog: additiveCatalog } = useAdditives()
  const additiveTypeOptions = useMemo(
    () => additives.map((item) => item?.mol_id).filter(Boolean),
    [additives],
  )
  const [additiveCounts, setAdditiveCounts] = useState({})
  const { weightMap: moleculeWeightMap } = useMoleculeWeights()
  const [binderWeightBySystem, setBinderWeightBySystem] = useState({})
  const [previewMolecule, setPreviewMolecule] = useState(null)
  // GAFF2 is the only active organic track (ReaxFF submission is not used). When
  // an inorganic species is added, the FF is automatically combined based on the
  // route, and AppliedForceFieldNote only displays the applied result.
  const ffType = 'bulk_ff_gaff2'
  const [previewBasis, setPreviewBasis] = useState({
    binderType: defaultForm.binder_types[0],
    structureSize: defaultForm.structure_sizes[0],
    agingState: defaultForm.aging_states[0],
    temperature: defaultForm.temperatures_k[0],
  })

  // Preview composition loading via shared hook
  const previewTempCode = useMemo(
    () => String(Math.round(previewBasis.temperature)).padStart(4, '0'),
    [previewBasis.temperature],
  )
  const {
    moleculeCounts: previewMoleculeCounts,
    loading: loadingComposition,
  } = useBinderComposition({
    binderType: previewBasis.binderType,
    structureSize: previewBasis.structureSize,
    agingState: previewBasis.agingState,
    tempCode: previewTempCode,
    enabled: Boolean(previewBasis.binderType),
  })

  const [validationError, setValidationError] = useState('')
  const [similarExistingAction, setSimilarExistingAction] = useState('unspecified')
  const [excludedExpIds, setExcludedExpIds] = useState(new Set())

  const validateMutation = useValidateBatchJobBinderCell()
  const createMutation = useCreateBatchJobBinderCell()
  const primaryStructureSize = form.structure_sizes[0] || 'X1'

  // E_inter precision analysis recommendation
  const realAdditiveTypesForRec = form.additive_types.filter((t) => t !== 'none')
  const { data: eInterRecommendation } = useEInterRecommendation(
    {
      workflow: 'batch_binder_cell',
      tier: form.tier || 'screening',
      has_additive: realAdditiveTypesForRec.length > 0,
    },
    form.binder_types.length > 0,
  )
  const [interactionAnalysisEnabled, setInteractionAnalysisEnabled] = useState(false)

  // ff_assignment route of the selected additives → automatic display of the
  // applied FF stack (not a selection). When an inorganic species
  // (inorganic_profile, e.g. SiO2) is included, INTERFACE FF is combined automatically.
  const additiveRoutes = useMemo(
    () =>
      form.additive_types
        .filter((t) => t !== 'none')
        .map((t) => additives.find((a) => a.mol_id === t)?.route)
        .filter(Boolean),
    [form.additive_types, additives],
  )
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

  const toggleListField = (field, value) => {
    setForm((prev) => {
      const exists = prev[field].includes(value)
      return {
        ...prev,
        [field]: exists
          ? prev[field].filter((item) => item !== value)
          : [...prev[field], value],
      }
    })
  }

  const toggleTemperature = (temp) => {
    setForm((prev) => {
      const exists = prev.temperatures_k.includes(temp)
      const nextTemps = exists
        ? prev.temperatures_k.filter((value) => value !== temp)
        : [...prev.temperatures_k, temp].sort((a, b) => a - b)
      return {
        ...prev,
        temperatures_k: nextTemps,
        temperature_priority: prev.temperature_priority.filter((value) => nextTemps.includes(value)),
      }
    })
  }

  const toggleTemperaturePriority = (temp) => {
    setForm((prev) => {
      const priorityExists = prev.temperature_priority.includes(temp)
      const nextTemps = prev.temperatures_k.includes(temp)
        ? prev.temperatures_k
        : [...prev.temperatures_k, temp].sort((a, b) => a - b)
      const nextPriority = priorityExists
        ? prev.temperature_priority.filter((value) => value !== temp)
        : [...prev.temperature_priority, temp].sort((a, b) => a - b)

      return {
        ...prev,
        temperatures_k: nextTemps,
        temperature_priority: nextPriority,
      }
    })
  }

  const toggleAdditiveType = (additiveType) => {
    const exists = form.additive_types.includes(additiveType)
    if (exists) {
      setForm((prev) => ({
        ...prev,
        additive_types: prev.additive_types.filter((item) => item !== additiveType),
      }))
      setAdditiveCounts((prev) => {
        const next = { ...prev }
        delete next[additiveType]
        return next
      })
      return
    }

    const defaultCount = Math.max(
      0,
      Number(additiveCatalog[additiveType]?.default_counts?.[primaryStructureSize] ?? 2),
    )
    setForm((prev) => ({
      ...prev,
      additive_types: [...prev.additive_types, additiveType],
    }))
    setAdditiveCounts((prev) => ({
      ...prev,
      [additiveType]: prev[additiveType] ?? defaultCount,
    }))
  }

  useEffect(() => {
    setForm((prev) => (prev.tier === computedRunTier ? prev : { ...prev, tier: computedRunTier }))
  }, [computedRunTier])

  useEffect(() => {
    const safeOptions = binderTypeOptions.length > 0 ? binderTypeOptions : FALLBACK_BINDER_TYPE_NAMES
    setForm((prev) => {
      const selected = (prev.binder_types || []).filter((value) => safeOptions.includes(value))
      return {
        ...prev,
        binder_types: selected.length > 0 ? selected : [safeOptions[0]],
      }
    })
  }, [binderTypeOptions])

  useEffect(() => {
    setPreviewBasis((prev) => {
      const next = { ...prev }
      const binderChoices = form.binder_types.length > 0 ? form.binder_types : [defaultForm.binder_types[0]]
      const sizeChoices = form.structure_sizes.length > 0 ? form.structure_sizes : [defaultForm.structure_sizes[0]]
      const agingChoices = form.aging_states.length > 0 ? form.aging_states : [defaultForm.aging_states[0]]
      const tempChoices = form.temperatures_k.length > 0 ? form.temperatures_k : [defaultForm.temperatures_k[0]]

      if (!binderChoices.includes(next.binderType)) next.binderType = binderChoices[0]
      if (!sizeChoices.includes(next.structureSize)) next.structureSize = sizeChoices[0]
      if (!agingChoices.includes(next.agingState)) next.agingState = agingChoices[0]
      if (!tempChoices.includes(next.temperature)) next.temperature = tempChoices[0]

      return next
    })
  }, [form.binder_types, form.structure_sizes, form.aging_states, form.temperatures_k])

  useEffect(() => {
    let isMounted = true

    const loadBinderWeights = async () => {
      if (
        form.binder_types.length === 0 ||
        form.structure_sizes.length === 0 ||
        form.aging_states.length === 0
      ) {
        setBinderWeightBySystem({})
        return
      }

      const jobs = []
      form.binder_types.forEach((binderType) => {
        form.structure_sizes.forEach((structureSize) => {
          form.aging_states.forEach((agingState) => {
            jobs.push({ binderType, structureSize, agingState })
          })
        })
      })

      try {
        const results = await Promise.all(
          jobs.map(async ({ binderType, structureSize, agingState }) => {
            const data = await getBinderComposition(binderType, structureSize, agingState, '0293')
            const molecules = data?.molecules || []
            const binderWeight = computeBinderWeightForSystem(molecules, agingState, moleculeWeightMap)

            return {
              key: `${binderType}|${agingState}|${structureSize}`,
              binderType,
              agingState,
              structureSize,
              binderWeight,
            }
          }),
        )

        if (!isMounted) return
        const next = {}
        results.forEach((item) => {
          next[item.key] = item
        })
        setBinderWeightBySystem(next)
      } catch {
        if (!isMounted) return
        setBinderWeightBySystem({})
      }
    }

    loadBinderWeights()
    return () => {
      isMounted = false
    }
  }, [form.aging_states, form.binder_types, form.structure_sizes, moleculeWeightMap])

  useEffect(() => {
    const options = additiveTypeOptions
    setForm((prev) => {
      const validTypes = (prev.additive_types || []).filter(
        (value) => value === 'none' || options.includes(value)
      )
      return {
        ...prev,
        additive_types: validTypes,
      }
    })
    setAdditiveCounts((prev) => {
      const next = {}
      Object.entries(prev).forEach(([key, value]) => {
        if (options.includes(key)) next[key] = value
      })
      return next
    })
  }, [additiveTypeOptions])

  const additiveSummary = useMemo(
    () => computeAdditiveSummary({
      additiveCatalog,
      additiveCounts,
      binderWeightBySystem,
      additiveTypes: form.additive_types,
      previewBasis,
    }),
    [additiveCatalog, additiveCounts, binderWeightBySystem, form.additive_types, previewBasis],
  )

  const compositionCards = useMemo(
    () => computeCompositionCards({
      previewMoleculeCounts,
      additiveTypes: form.additive_types,
      additiveCatalog,
      additiveCounts,
    }),
    [additiveCatalog, additiveCounts, form.additive_types, previewMoleculeCounts],
  )

  const previewTotals = useMemo(
    () => computePreviewTotals(compositionCards),
    [compositionCards],
  )

  // Build interaction analysis config based on recommendation and toggle state
  const interactionAnalysisConfig = useMemo(() => {
    const level = eInterRecommendation?.level
    if (!level || level === 'none') return null
    // For required level, always enabled; for others, follow user toggle
    const enabled = level === 'required' || interactionAnalysisEnabled
    if (!enabled) return null
    // Codex #2: normalize empty metrics to default ['e_inter_total']
    const rawMetrics = eInterRecommendation?.affected_metrics
    const metrics = rawMetrics?.length ? rawMetrics : ['e_inter_total']
    return {
      enabled: true,
      metrics,
      auto_trigger_rerun: true,
    }
  }, [eInterRecommendation, interactionAnalysisEnabled])

  const requestPayload = useMemo(
    () => buildRequestPayload({
      form,
      ffType,
      additiveSummary,
      selectedStages,
      viscosityTemps,
      similarExistingAction,
      excludedExpIds,
      buildStageOverrides,
      buildStageRequests,
      buildEquilibrationSettings,
      interactionAnalysis: interactionAnalysisConfig,
      eIntraMethod: effectiveEIntraMethod,
    }),
    [additiveSummary, buildEquilibrationSettings, buildStageOverrides, buildStageRequests, effectiveEIntraMethod, excludedExpIds, ffType, form, interactionAnalysisConfig, selectedStages, similarExistingAction, viscosityTemps],
  )

  // Reset similarity decision and exclusions when form changes
  useEffect(() => {
    setSimilarExistingAction('unspecified')
    setExcludedExpIds(new Set())
  }, [
    form.binder_types,
    form.structure_sizes,
    form.aging_states,
    form.temperatures_k,
    form.additive_types,
  ])

  const latestResponse = validateMutation.data || createMutation.data
  const scenarioPreview = validateMutation.data
  const effectiveSimilarCount = (scenarioPreview?.jobs || [])
    .filter(j => j.similar_existing && j.status !== 'duplicate' && !excludedExpIds.has(j.exp_id))
    .length
  const requiresSimilarityDecision = scenarioPreview?.requires_similarity_decision && effectiveSimilarCount > 0
  const toggleExclude = (expId) => {
    setExcludedExpIds(prev => {
      const next = new Set(prev)
      next.has(expId) ? next.delete(expId) : next.add(expId)
      return next
    })
  }
  const excludeAllSimilar = () => {
    const ids = scenarioPreview?.jobs
      ?.filter(j => j.similar_existing && j.status !== 'duplicate')
      ?.map(j => j.exp_id) || []
    setExcludedExpIds(prev => new Set([...prev, ...ids]))
  }
  const clearExclusions = () => setExcludedExpIds(new Set())
  const additiveTypes = form.additive_types
  const realAdditiveTypes = additiveTypes.filter((t) => t !== 'none')
  const hasControl = additiveTypes.includes('none')
  // In binder cell mode, each additive has a fixed molecule count (no concentration axis)
  // So additiveComboCount = number of additives + control (if any)
  const additiveComboCount = realAdditiveTypes.length > 0
    ? realAdditiveTypes.length + (hasControl ? 1 : 0)
    : 1
  const axisCounts = [
    form.binder_types.length,
    form.structure_sizes.length,
    form.aging_states.length,
    form.temperatures_k.length,
    1,
  ]
  const totalJobCount = axisCounts.some((count) => count === 0)
    ? 0
    : axisCounts.reduce((acc, count) => acc * count, 1) * additiveComboCount
  const selectedStageNames = useMemo(() => {
    return Object.entries(stageConfig)
      .filter(([stage, cfg]) => selectedStages[stage] && !cfg.disabled)
      .map(([, cfg]) => cfg.name)
  }, [selectedStages, stageConfig])

  const handleSubmitBatchJob = async () => {
    if (!requestPayload.payload) {
      setValidationError(requestPayload.error || 'Invalid batch job request.')
      return
    }

    // Check if similarity decision is required
    if (requiresSimilarityDecision && similarExistingAction === 'unspecified') {
      setValidationError('Please select a priority handling option for jobs with similar experiments.')
      return
    }

    // P0: Submit goes directly to create endpoint — NO precompute cache call.
    // Backend FF gate returns ff_blocked_items if artifacts are missing.
    // Users must generate artifacts via Molecules catalog BEFORE submit.
    setValidationError('')
    try {
      await createMutation.mutateAsync(requestPayload.payload)
    } catch {
      // Error surface is handled by createMutation.error panel.
    }
  }

  // chipButtonClass imported from lib/chipButton (fontWeight='normal' for this page)
  const chipButtonClass = (active, colorScheme = 'blue') =>
    chipButtonClassFn(active, { colorScheme, fontWeight: 'normal' })

  return (
    <div className="space-y-4">
      <PageHeader
        routeKey={ROUTE_KEYS.BATCH_JOB_BINDER_CELL}
        subtitle="Configure and submit batch Binder Cell jobs."
      />

      <div className="card p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-stretch">
          <div className="text-sm text-slate-300 md:col-span-2 flex flex-col">
            <div className="text-sm font-semibold mb-1">Protocol Timeline</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1 flex flex-col justify-center">
              <ProtocolTimeline
                selectedStages={selectedStages}
                stageConfig={timelineStageConfig}
                legendPosition="inline"
              />
            </div>
          </div>
          <BatchJobBinderCellAxisSelectionPanel
            binderTypeOptions={binderTypeOptions}
            structureSizeOptions={STRUCTURE_SIZE_OPTIONS}
            agingStateOptions={AGING_STATE_OPTIONS}
            form={form}
            toggleListField={toggleListField}
            chipButtonClass={chipButtonClass}
          />
        </div>

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
          <BatchJobBinderCellCompositionPanel
            loadingComposition={loadingComposition}
            previewTotals={previewTotals}
            compositionCards={compositionCards}
            onPreviewMolecule={(card) => setPreviewMolecule({ mol_id: card.molId, name: card.title })}
            previewBasis={previewBasis}
            setPreviewBasis={setPreviewBasis}
            form={form}
            defaultForm={defaultForm}
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[1.7fr_0.75fr_0.75fr_0.75fr_0.75fr] gap-3 items-stretch">
          <BatchJobTemperaturePanel
            temperatureOptions={expDefaults?.available_temperature_options_k ?? TEMPERATURE_PRESET_OPTIONS}
            form={form}
            toggleTemperature={toggleTemperature}
            toggleTemperaturePriority={toggleTemperaturePriority}
            chipButtonClass={chipButtonClass}
          />
          <BatchJobBinderCellAdditivesPanel
            additiveTypeOptions={additiveTypeOptions}
            selectedAdditiveTypes={form.additive_types}
            toggleAdditiveType={toggleAdditiveType}
            chipButtonClass={chipButtonClass}
            additiveSummary={additiveSummary}
            additiveCatalog={additiveCatalog}
            setAdditiveCounts={setAdditiveCounts}
            additiveSummaryGrid={ADDITIVE_SUMMARY_GRID}
          />
          <BatchJobFFDensityPanel
            ffType={ffType}
            form={form}
            setForm={setForm}
            additiveRoutes={additiveRoutes}
          />
          <BatchJobSeedCachePanel
            form={form}
            setForm={setForm}
            defaultEIntraMethodLabel={getSubmissionEIntraMethodLabel(defaultEIntraMethod)}
            effectiveEIntraMethodLabel={effectiveEIntraMethodLabel}
            eIntraMethodOverride={selectedEIntraMethod}
            setEIntraMethodOverride={setSelectedEIntraMethod}
            eIntraMethodOptions={SUBMISSION_E_INTRA_METHOD_OPTIONS}
          />
        </div>

        <BatchJobBinderCellSubmissionPanel
          form={form}
          totalJobCount={totalJobCount}
          additiveComboCount={additiveComboCount}
          computedRunTier={computedRunTier}
          selectedStageNames={selectedStageNames}
          ffType={ffType}
          selectedStages={selectedStages}
          viscosityTemps={viscosityTemps}
          requestPayload={requestPayload}
          setValidationError={setValidationError}
          validateMutation={validateMutation}
          createMutation={createMutation}
          onSubmitBatchJob={handleSubmitBatchJob}
          eInterRecommendation={eInterRecommendation}
          onInteractionAnalysisChange={setInteractionAnalysisEnabled}
          effectiveEIntraMethodLabel={effectiveEIntraMethodLabel}
        />

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <BatchJobBinderCellScenarioPreviewPanel
            scenarioPreview={scenarioPreview}
            pending={validateMutation.isPending}
            error={
              validateMutation.isError
                ? (validateMutation.error?.response?.data?.detail || validateMutation.error?.message || 'Failed to build scenario')
                : ''
            }
            additiveCatalog={additiveCatalog}
            binderCodeMap={BINDER_CODE}
            agingCodeMap={AGING_CODE}
            excludedExpIds={excludedExpIds}
          />
        </div>
      </div>

      {validationError && (
        <div className="card p-3 text-amber-300 text-sm">
          {validationError}
        </div>
      )}

      {(validateMutation.error || createMutation.error) && (
        <div className="card p-3 text-amber-300 text-sm">
          {validateMutation.error?.response?.data?.detail || createMutation.error?.response?.data?.detail || 'Request failed'}
        </div>
      )}

      <BatchJobBinderCellResponsePanel
        latestResponse={latestResponse}
        isSubmission={Boolean(createMutation.data)}
        excludedExpIds={excludedExpIds}
        onToggleExclude={toggleExclude}
        onExcludeAllSimilar={excludeAllSimilar}
        onClearExclusions={clearExclusions}
      />

      {requiresSimilarityDecision && !createMutation.data && (
        <div className="card p-4 border-2 border-cyan-500/50">
          <div className="text-sm font-semibold text-cyan-300 mb-3">
            Similar Experiments Detected
          </div>
          <div className="text-sm text-slate-300 mb-4">
            <strong className="text-cyan-400">{effectiveSimilarCount}</strong> job(s) have similar completed experiments in the database.
            Would you like to lower the priority of these jobs?
          </div>
          <div className="flex flex-wrap gap-3">
            {SIMILAR_EXISTING_ACTION_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={clsx(
                  'px-4 py-2 rounded-lg text-sm border transition-colors',
                  similarExistingAction === option.value
                    ? 'bg-cyan-500/30 border-cyan-500 text-cyan-200'
                    : 'bg-slate-700/40 border-slate-600 text-slate-300 hover:bg-slate-700'
                )}
                onClick={() => setSimilarExistingAction(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
          {similarExistingAction !== 'unspecified' && (
            <div className="mt-3 text-xs text-slate-400">
              {SIMILAR_EXISTING_ACTION_OPTIONS.find((o) => o.value === similarExistingAction)?.description}
            </div>
          )}
        </div>
      )}

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

export default BatchJobBinderCellPage
