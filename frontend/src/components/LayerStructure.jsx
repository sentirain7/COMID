import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import ProtocolTimeline from './ProtocolTimeline'
import ProtocolStagesPanel from './ProtocolStagesPanel'
import useProtocolStages from '../hooks/useProtocolStages'
import TemperatureSelectorHybrid from './shared/TemperatureSelectorHybrid'
import { NotificationBanner, PrecisionAnalysisPanel } from './shared'
import PageHeader from './shared/PageHeader'
import { useNotification } from '../hooks/useNotification'
import { ROUTE_KEYS } from '../navigation/routeMeta'
import {
  useLayeredStructurePreview,
  useLayeredStructureSubmit,
  useLayerSources,
} from '../hooks/useApi'
import { getTodaySeed } from '../lib/seed'
import { useSubmissionEIntraMethod } from '../hooks/useSubmissionEIntraMethod'

import {
  LAYER_REQUIRED_STAGES,
  LAYER_STAGES,
  SECTION_TITLE_CLASS,
} from './layer-structure/config'
import {
  createLayerRow,
  autoMatchCrystalLayers,
  computeLayerXYErrors,
  generateAutoName,
} from './layer-structure/helpers'
import {
  buildLayerPayload,
  buildSubmitPayload,
  hasLayersMissingSources,
} from './layer-structure/payloadBuilder'
import LayerComposerPanel from './layer-structure/LayerComposerPanel'
import LayerSettingsPanel from './layer-structure/LayerSettingsPanel'
import LayerPreviewPanel from './layer-structure/LayerPreviewPanel'
import TensileParametersPanel from './layer-structure/TensileParametersPanel'
import {
  SUBMISSION_E_INTRA_METHOD_OPTIONS,
  getSubmissionEIntraMethodLabel,
} from '../lib/eIntraMethod'

function LayeredStructurePage() {
  const location = useLocation()
  const navigate = useNavigate()
  const isBatchRoute = location.pathname.startsWith('/batch-job/')

  // layers[0] = bottom (z=0, substrate), layers[N-1] = top.
  // Default: crystal substrate at bottom, binder on top.
  const [layers, setLayers] = useState(() => [
    createLayerRow('crystal_structure'),
    createLayerRow('interface_molecule_cell'),
    createLayerRow('binder_cell'),
  ])
  const [ffType, setFfType] = useState('bulk_ff_gaff2')
  const [temperatureK, setTemperatureK] = useState(298)
  const [pressureAtm, setPressureAtm] = useState(1.0)
  const [xyTolerance, setXyTolerance] = useState('5.0')
  const [xyToZRatio, setXyToZRatio] = useState(1.2)
  const [interLayerGap, setInterLayerGap] = useState(2.0)
  const [zVacuum, setZVacuum] = useState(20.0)
  const [seed, setSeed] = useState(() => getTodaySeed())
  const { notification, notify, dismiss } = useNotification()
  const {
    defaultEIntraMethod,
    effectiveEIntraMethod,
    selectedEIntraMethod,
    setSelectedEIntraMethod,
  } = useSubmissionEIntraMethod()
  const [tensilePullVelocity, setTensilePullVelocity] = useState(0.00005)
  const [tensileGripThickness, setTensileGripThickness] = useState(20.0)
  const [tensileMaxStrain, setTensileMaxStrain] = useState(0.5)

  const {
    selectedStages,
    stageConfig,
    stageDurations,
    loadingStages,
    toggleStage,
    handleDurationChange,
    resetDurationToDefault,
    isDurationModified,
    buildStageOverrides,
    timelineStageConfig,
    addViscosityTemp,
    removeViscosityTemp,
    updateViscosityTemp,
  } = useProtocolStages({ defaultChainKey: 'tensile_layer', requiredStages: LAYER_REQUIRED_STAGES })

  const binderSources = useLayerSources('binder_cell', 200, 'library')
  const interfaceMolSources = useLayerSources('interface_molecule_cell', 200, 'library')
  const crystalSources = useLayerSources('crystal_structure', 200, 'library')

  const previewMutation = useLayeredStructurePreview()
  const submitMutation = useLayeredStructureSubmit()

  // Codex #5: Use backend preview response as SSOT for recommendation
  // Backend can detect water/ion from layer sources metadata
  const previewData = previewMutation.data

  // SSOT: layered precision recommendation comes only from backend preview.
  const eInterRecommendation = previewData?.e_inter_recommendation || null
  const [interactionAnalysisEnabled, setInteractionAnalysisEnabled] = useState(false)

  // Build interaction analysis config based on recommendation and toggle state
  const interactionAnalysisConfig = useMemo(() => {
    const level = eInterRecommendation?.level
    if (!level || level === 'none') return null
    // For required level, always enabled; for others, follow user toggle
    const enabled = level === 'required' || interactionAnalysisEnabled
    if (!enabled) return null
    // Codex #2/#4: v1 only supports e_inter_total
    return {
      enabled: true,
      metrics: ['e_inter_total'],
      auto_trigger_rerun: true,
    }
  }, [eInterRecommendation, interactionAnalysisEnabled])

  const sourceCatalog = useMemo(
    () => ({
      binder_cell: binderSources.data?.items || [],
      interface_molecule_cell: interfaceMolSources.data?.items || [],
      crystal_structure: crystalSources.data?.items || [],
    }),
    [binderSources.data, interfaceMolSources.data, crystalSources.data]
  )

  const layeredStageConfig = useMemo(
    () =>
      LAYER_STAGES.reduce((acc, stage) => {
        if (stageConfig[stage]) acc[stage] = stageConfig[stage]
        return acc
      }, {}),
    [stageConfig]
  )

  const layeredStageDurations = useMemo(
    () =>
      LAYER_STAGES.reduce((acc, stage) => {
        if (stageDurations[stage]) acc[stage] = stageDurations[stage]
        return acc
      }, {}),
    [stageDurations]
  )

  const layeredSelectedStages = useMemo(
    () =>
      LAYER_STAGES.reduce((acc, stage) => {
        acc[stage] = selectedStages[stage] !== false
        return acc
      }, {}),
    [selectedStages]
  )

  const layeredTimelineStageConfig = useMemo(
    () =>
      LAYER_STAGES.reduce((acc, stage) => {
        if (timelineStageConfig[stage]) acc[stage] = timelineStageConfig[stage]
        return acc
      }, {}),
    [timelineStageConfig]
  )

  // Per-layer XY error: crystal layers compare against nearest non-crystal above
  const layerXYErrors = useMemo(
    () => computeLayerXYErrors(layers, sourceCatalog),
    [layers, sourceCatalog]
  )

  const autoGeneratedName = useMemo(
    () => generateAutoName(layers, temperatureK, ffType, pressureAtm),
    [layers, ffType, temperatureK, pressureAtm]
  )

  const handleTemperatureChange = (nextTemp) => {
    setTemperatureK(nextTemp)
  }

  const canAddLayer = layers.length < 5
  const canRemoveLayer = layers.length > 2

  const handleLayerField = (rowId, key, value) => {
    setLayers((prev) => {
      let next = prev.map((row) => {
        if (row.rowId !== rowId) return row
        if (key === 'sourceType') {
          return { ...row, sourceType: value, sourceId: '', autoMatchMaterial: '', autoSelected: false }
        }
        if (key === 'autoMatchMaterial') {
          return { ...row, autoMatchMaterial: value, sourceId: '', autoSelected: false }
        }
        if (key === 'sourceId') {
          return { ...row, sourceId: value, autoMatchMaterial: '', autoSelected: false }
        }
        return { ...row, [key]: value }
      })

      if (key === 'sourceId' && value) {
        const changedRow = next.find((r) => r.rowId === rowId)
        if (changedRow && changedRow.sourceType !== 'crystal_structure') {
          next = autoMatchCrystalLayers(next, sourceCatalog)
        }
      }

      return next
    })
  }

  const moveLayer = (index, direction) => {
    setLayers((prev) => {
      const target = index + direction
      if (target < 0 || target >= prev.length) return prev
      const next = [...prev]
      const [item] = next.splice(index, 1)
      next.splice(target, 0, item)
      return next
    })
  }

  const removeLayer = (rowId) => {
    if (!canRemoveLayer) return
    setLayers((prev) => prev.filter((row) => row.rowId !== rowId))
  }

  const addLayer = () => {
    if (!canAddLayer) return
    setLayers((prev) => [...prev, createLayerRow('binder_cell')])
  }

  const handlePreview = async () => {
    dismiss()
    if (hasLayersMissingSources(layers)) {
      notify('warning', 'Select a source (or auto-match material) for every layer before preview.')
      return
    }
    try {
      await previewMutation.mutateAsync(buildLayerPayload(layers, xyTolerance, xyToZRatio, interLayerGap))
    } catch {
      // handled in UI
    }
  }

  const handleSubmit = async () => {
    dismiss()
    if (hasLayersMissingSources(layers, { requireSourceId: true })) {
      notify('warning', 'Select a source for every layer before submit.')
      return
    }
    try {
      const stageOverrides = buildStageOverrides()
      const result = await submitMutation.mutateAsync(
        buildSubmitPayload({
          autoGeneratedName,
          layers,
          xyTolerance,
          xyToZRatio,
          interLayerGap,
          ffType,
          temperatureK,
          pressureAtm,
          zVacuum,
          seed,
          stageOverrides,
          layeredSelectedStages,
          tensilePullVelocity,
          tensileGripThickness,
          tensileMaxStrain,
          interactionAnalysis: interactionAnalysisConfig,
          eIntraMethod: effectiveEIntraMethod,
        })
      )
      notify('success', `Submitted: ${result.exp_id} (job ${result.job_id})`)
      navigate('/')
    } catch {
      // handled in UI
    }
  }

  // previewData already declared above (line 90) for SSOT recommendation
  const previewError = previewMutation.error?.response?.data?.detail || previewMutation.error?.message
  const submitError = submitMutation.error?.response?.data?.detail || submitMutation.error?.message

  useEffect(() => {
    if (previewError) notify('error', previewError)
  }, [previewError, notify])

  useEffect(() => {
    if (submitError) notify('error', submitError)
  }, [submitError, notify])

  if (isBatchRoute) {
    return (
      <div className="space-y-4">
        <PageHeader routeKey={ROUTE_KEYS.BATCH_JOB_LAYERED_STRUCTURE} />
        <div className="card p-4 text-sm text-slate-300">
          Batch Job layered structure is not enabled yet. Use Single Job {'>'} Layered Structure.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <NotificationBanner notification={notification} onDismiss={dismiss} />
      <PageHeader
        routeKey={ROUTE_KEYS.SINGLE_JOB_LAYERED_STRUCTURE}
        subtitle="Compose 2-5 layers from Binder Cell, Amorphous Cell, and Crystal Structure sources."
      />

      <div className="card p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-start">
          <div className="md:col-span-2 space-y-3">
            <div className="text-sm text-slate-300 flex flex-col">
              <div className={SECTION_TITLE_CLASS}>Protocol Timeline</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
                <ProtocolTimeline
                  selectedStages={layeredSelectedStages}
                  stageConfig={layeredTimelineStageConfig}
                  legendPosition="inline"
                  targetTemperatureK={temperatureK}
                  targetPressureAtm={pressureAtm}
                />
              </div>
            </div>

            <ProtocolStagesPanel
              stageConfig={layeredStageConfig}
              stageDurations={layeredStageDurations}
              selectedStages={layeredSelectedStages}
              loading={loadingStages}
              compact
              titleClassName={`${SECTION_TITLE_CLASS} flex items-center gap-2`}
              onToggleStage={toggleStage}
              onDurationChange={handleDurationChange}
              onResetDuration={resetDurationToDefault}
              isDurationModified={isDurationModified}
              viscosityTemps={[]}
              onViscosityTempChange={updateViscosityTemp}
              onAddViscosityTemp={addViscosityTemp}
              onRemoveViscosityTemp={removeViscosityTemp}
              targetTemperatureK={temperatureK}
              targetPressureAtm={pressureAtm}
            />

            {layeredSelectedStages.tensile_pull && (
              <TensileParametersPanel
                tensilePullVelocity={tensilePullVelocity}
                setTensilePullVelocity={setTensilePullVelocity}
                tensileGripThickness={tensileGripThickness}
                setTensileGripThickness={setTensileGripThickness}
                tensileMaxStrain={tensileMaxStrain}
                setTensileMaxStrain={setTensileMaxStrain}
              />
            )}
          </div>

          <div className="md:col-span-2 space-y-3">
            <LayerSettingsPanel
              ffType={ffType}
              setFfType={setFfType}
              pressureAtm={pressureAtm}
              setPressureAtm={setPressureAtm}
              xyTolerance={xyTolerance}
              setXyTolerance={setXyTolerance}
              xyToZRatio={xyToZRatio}
              setXyToZRatio={setXyToZRatio}
              zVacuum={zVacuum}
              setZVacuum={setZVacuum}
              seed={seed}
              setSeed={setSeed}
              defaultEIntraMethodLabel={getSubmissionEIntraMethodLabel(defaultEIntraMethod)}
              effectiveEIntraMethodLabel={getSubmissionEIntraMethodLabel(effectiveEIntraMethod)}
              eIntraMethodOverride={selectedEIntraMethod}
              setEIntraMethodOverride={setSelectedEIntraMethod}
              eIntraMethodOptions={SUBMISSION_E_INTRA_METHOD_OPTIONS}
              previewData={previewData}
            />

            {eInterRecommendation && (
              <PrecisionAnalysisPanel
                recommendation={eInterRecommendation}
                onChange={setInteractionAnalysisEnabled}
              />
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-stretch">
          <div className="md:col-span-2 space-y-3">
            <div className="text-sm text-slate-300 flex flex-col">
              <div className={SECTION_TITLE_CLASS}>Target Temperature (K)</div>
              <div className="text-[9px] text-slate-500 mb-0.5">
                Applies to equilibration (NVT/NPT) and tensile pull stages.
                Annealing cycles ramp between this and high temperature.
              </div>
              <TemperatureSelectorHybrid
                value={temperatureK}
                onChange={handleTemperatureChange}
                presetColumns={7}
                compact
                showTitle={false}
              />
            </div>
            <LayerComposerPanel
              layers={layers}
              sourceCatalog={sourceCatalog}
              layerXYErrors={layerXYErrors}
              interLayerGap={interLayerGap}
              setInterLayerGap={setInterLayerGap}
              canAddLayer={canAddLayer}
              canRemoveLayer={canRemoveLayer}
              addLayer={addLayer}
              removeLayer={removeLayer}
              moveLayer={moveLayer}
              handleLayerField={handleLayerField}
              previewMutation={previewMutation}
              submitMutation={submitMutation}
              handlePreview={handlePreview}
              handleSubmit={handleSubmit}
            />
          </div>

          <LayerPreviewPanel
            previewData={previewData}
            previewMutation={previewMutation}
          />
        </div>
      </div>
    </div>
  )
}

export default LayeredStructurePage
