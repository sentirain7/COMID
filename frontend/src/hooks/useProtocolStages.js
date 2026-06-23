import { useEffect, useMemo, useState } from 'react'
import { getDefaultStages } from '../api/client'
import {
  buildEquilibrationSettingsPayload,
  buildEquilibrationDefaults,
  EQUILIBRATION_STAGE_KEYS,
  getFallbackStageDefinition,
  getFallbackStageKeys,
  getOptionalStageKeys,
  getStageSelectionDefault,
  isVirtualSelectorStage,
  LAYER_CHAIN_KEYS,
  resolveComputedRunTier,
} from '../lib/protocolStages'

export default function useProtocolStages({ defaultChainKey, requiredStages } = {}) {
  const [selectedStages, setSelectedStages] = useState({})
  const [stageConfig, setStageConfig] = useState({})
  const [stageDefaults, setStageDefaults] = useState({})
  const [stageDurations, setStageDurations] = useState({})
  const [loadingStages, setLoadingStages] = useState(false)
  const [viscosityTemps, setViscosityTemps] = useState([298])
  // Equilibration stage parameters (temperature, pressure)
  const [equilibrationParams, setEquilibrationParams] = useState({})

  // computedRunTier: for bulk workflows this is the actual RunTier;
  // for layer workflows (defaultChainKey='tensile_layer') it serves as the
  // stages API chain key. LayerStructure must NOT use this as submit run_tier.
  const computedRunTier = useMemo(
    () => resolveComputedRunTier(selectedStages, stageConfig, defaultChainKey),
    [defaultChainKey, selectedStages, stageConfig]
  )

  useEffect(() => {
    const fetchDefaultStages = async () => {
      setLoadingStages(true)
      try {
        const data = await getDefaultStages(computedRunTier, { includeOptional: true })
        const config = {}
        const defaults = {}
        const durations = {}

        const normalizeStage = (stageName, stage = {}) => {
          const fallback = getFallbackStageDefinition(stageName) || {}
          const rawUiMetadata = stage.ui_metadata || {}
          const parameterFields = rawUiMetadata.parameter_fields || fallback.uiMetadata?.parameterFields || []
          return {
            config: {
              name: stage.display_name || fallback.displayName || stageName,
              compactDisplayName:
                stage.compact_display_name || fallback.compactDisplayName || stage.display_name || fallback.displayName || stageName,
              type: stage.type || fallback.type || 'npt',
              editable: stage.editable ?? true,
              required: requiredStages?.length
                ? requiredStages.includes(stageName)
                : !(stage.optional ?? fallback.optional ?? false),
              disabled: false,
              condition: stage.condition || null,
              shortName: stage.short_name || fallback.shortName || stageName,
              color: stage.color || fallback.color || null,
              optional: stage.optional ?? fallback.optional ?? false,
              editableFields: stage.editable_fields || fallback.editableFields || ['duration'],
              bounds: stage.bounds || fallback.bounds || {},
              uiMetadata: {
                ...(fallback.uiMetadata || {}),
                ...rawUiMetadata,
                defaultTemperatureK:
                  rawUiMetadata.default_temperature_K
                  ?? fallback.uiMetadata?.defaultTemperatureK,
                defaultPressureAtm:
                  rawUiMetadata.default_pressure_atm
                  ?? fallback.uiMetadata?.defaultPressureAtm,
                submitTier: rawUiMetadata.submit_tier ?? fallback.uiMetadata?.submitTier,
                virtualSelector:
                  rawUiMetadata.virtual_selector
                  ?? fallback.uiMetadata?.virtualSelector
                  ?? false,
                equilibrationPayload: rawUiMetadata.equilibration_payload
                  ? {
                    durationKey: rawUiMetadata.equilibration_payload.duration_key,
                    params: rawUiMetadata.equilibration_payload.params || {},
                  }
                  : fallback.uiMetadata?.equilibrationPayload,
                parameterFields: parameterFields.map((field) => ({
                  field: field.field,
                  label: field.label,
                  unit: field.unit,
                  step: field.step ?? 1,
                  parseAs: field.parse_as || field.parseAs || 'float',
                })),
                selectorDescription:
                  rawUiMetadata.selector_description
                  ?? fallback.uiMetadata?.selectorDescription
                  ?? null,
              },
              orderIndex: stage.order_index ?? fallback.orderIndex ?? 0,
            },
            defaults: {
              ps: stage.duration_ps ?? fallback.durationPs ?? null,
              steps: stage.duration_steps ?? fallback.durationSteps ?? null,
            },
          }
        }

        data.stages.forEach((stage) => {
          const normalized = normalizeStage(stage.name, stage)
          config[stage.name] = normalized.config
          defaults[stage.name] = normalized.defaults
          durations[stage.name] = normalized.defaults
        })

        for (const stageName of getOptionalStageKeys(computedRunTier)) {
          if (config[stageName]) continue
          const normalized = normalizeStage(stageName)
          config[stageName] = normalized.config
          defaults[stageName] = normalized.defaults
          durations[stageName] = normalized.defaults
        }

        setStageConfig(config)
        setStageDefaults(defaults)
        setStageDurations(durations)
        setSelectedStages((prev) => {
          const next = {}
          Object.keys(config).forEach((stageName) => {
            if (Object.prototype.hasOwnProperty.call(prev, stageName)) {
              next[stageName] = prev[stageName]
              return
            }
            next[stageName] = getStageSelectionDefault(
              stageName,
              config[stageName],
              requiredStages || [],
              defaultChainKey || computedRunTier
            )
          })
          return next
        })
        setEquilibrationParams((prev) => {
          const nextDefaults = buildEquilibrationDefaults(config, durations)
          return {
            high_temp_nvt: {
              ...nextDefaults.high_temp_nvt,
              ...(prev.high_temp_nvt || {}),
            },
            high_pressure_npt: {
              ...nextDefaults.high_pressure_npt,
              ...(prev.high_pressure_npt || {}),
            },
          }
        })
      } catch (err) {
        console.error('Failed to load stage defaults:', err)
        const fallbackStageKeys = getFallbackStageKeys(defaultChainKey || computedRunTier)
        const fallbackConfig = {}
        const fallbackDefaults = {}
        fallbackStageKeys.forEach((stageName) => {
          const fallback = getFallbackStageDefinition(stageName)
          if (!fallback) return
          fallbackConfig[stageName] = {
            name: fallback.displayName,
            type: fallback.type,
            editable: true,
            required: requiredStages?.length
              ? requiredStages.includes(stageName)
              : !fallback.optional,
            disabled: false,
            condition: null,
            shortName: fallback.shortName,
            color: fallback.color,
            optional: fallback.optional,
            editableFields: fallback.editableFields,
            bounds: fallback.bounds,
            uiMetadata: fallback.uiMetadata,
            orderIndex: fallback.orderIndex,
          }
          fallbackDefaults[stageName] = {
            ps: fallback.durationPs,
            steps: fallback.durationSteps,
          }
        })
        setStageConfig(fallbackConfig)
        setStageDefaults(fallbackDefaults)
        setStageDurations({ ...fallbackDefaults })
        setSelectedStages((prev) => {
          const next = {}
          Object.keys(fallbackConfig).forEach((stageName) => {
            next[stageName] = Object.prototype.hasOwnProperty.call(prev, stageName)
              ? prev[stageName]
              : getStageSelectionDefault(
                stageName,
                fallbackConfig[stageName],
                requiredStages || [],
                defaultChainKey || computedRunTier
              )
          })
          return next
        })
        setEquilibrationParams(buildEquilibrationDefaults(fallbackConfig, fallbackDefaults))
      } finally {
        setLoadingStages(false)
      }
    }

    fetchDefaultStages()
  }, [computedRunTier, defaultChainKey, requiredStages])

  const toggleStage = (stage) => {
    const cfg = stageConfig[stage]
    if (!cfg || cfg.required || cfg.disabled) return
    if (EQUILIBRATION_STAGE_KEYS.has(stage)) {
      const bothExist = stageConfig.high_temp_nvt && stageConfig.high_pressure_npt
      if (bothExist) {
        const nextValue = !selectedStages[stage]
        setSelectedStages((prev) => ({
          ...prev,
          high_temp_nvt: nextValue,
          high_pressure_npt: nextValue,
        }))
        return
      }
      // Fall through to individual toggle (layered workflow)
    }
    setSelectedStages((prev) => ({ ...prev, [stage]: !prev[stage] }))
  }

  const handleDurationChange = (stage, value, unit) => {
    setStageDurations((prev) => ({
      ...prev,
      [stage]: {
        ...prev[stage],
        [unit]: value,
      },
    }))
  }

  const resetDurationToDefault = (stage) => {
    setStageDurations((prev) => ({
      ...prev,
      [stage]: { ...stageDefaults[stage] },
    }))
  }

  const isDurationModified = (stage) => {
    const current = stageDurations[stage]
    const def = stageDefaults[stage]
    if (!current || !def) return false
    return current.ps !== def.ps || current.steps !== def.steps
  }

  const isLayerChain = LAYER_CHAIN_KEYS.has(defaultChainKey)

  const buildStageOverrides = () =>
    Object.entries(stageDurations)
      .filter(([stage]) => (
        selectedStages[stage]
        && isDurationModified(stage)
        // In layer chains, equilibration stages are real chain stages (not injected),
        // so their duration overrides must be sent as stage_durations.
        && (isLayerChain || !EQUILIBRATION_STAGE_KEYS.has(stage))
        && !isVirtualSelectorStage(stageConfig, stage)
      ))
      .map(([stage, d]) => ({
        stage_name: stage,
        duration_ps: d.ps,
        duration_steps: d.steps,
      }))

  const buildStageRequests = () => {
    const requests = []
    const equilibrationEnabled = Boolean(selectedStages.high_temp_nvt || selectedStages.high_pressure_npt)
    const defaultEqParams = buildEquilibrationDefaults(stageConfig, stageDefaults)

    requests.push({
      stage_key: 'high_temp_nvt',
      enabled: equilibrationEnabled,
      duration_ps: stageDurations.high_temp_nvt?.ps ?? defaultEqParams.high_temp_nvt?.duration_ps ?? null,
      duration_steps: null,
      params_override: {
        temperature_K: equilibrationParams.high_temp_nvt?.temperature_K ?? defaultEqParams.high_temp_nvt?.temperature_K ?? 500,
      },
    })
    requests.push({
      stage_key: 'high_pressure_npt',
      enabled: equilibrationEnabled,
      duration_ps: stageDurations.high_pressure_npt?.ps ?? defaultEqParams.high_pressure_npt?.duration_ps ?? null,
      duration_steps: null,
      params_override: {
        temperature_K: equilibrationParams.high_pressure_npt?.temperature_K ?? defaultEqParams.high_pressure_npt?.temperature_K ?? 500,
        pressure_atm: equilibrationParams.high_pressure_npt?.pressure_atm ?? defaultEqParams.high_pressure_npt?.pressure_atm ?? 100,
      },
    })

    Object.entries(stageDurations)
      .filter(([stage]) => !EQUILIBRATION_STAGE_KEYS.has(stage))
      .forEach(([stage, d]) => {
        const isSelected = Boolean(selectedStages[stage])
        const modified = isDurationModified(stage)
        const cfg = stageConfig[stage]
        if (!cfg && !modified) return
        if (!isSelected && !modified) return
        const canSendDuration = modified && !isVirtualSelectorStage(stageConfig, stage)

        requests.push({
          stage_key: stage,
          enabled: isSelected,
          duration_ps: canSendDuration ? (d?.ps ?? null) : null,
          duration_steps: canSendDuration ? (d?.steps ?? null) : null,
          params_override: null,
        })
      })

    return requests
  }

  const addViscosityTemp = () => {
    setViscosityTemps((prev) => (prev.length < 5 ? [...prev, 298] : prev))
  }

  const removeViscosityTemp = (index) => {
    setViscosityTemps((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev))
  }

  const updateViscosityTemp = (index, value) => {
    setViscosityTemps((prev) => {
      const next = [...prev]
      next[index] = value
      return next
    })
  }

  const updateEquilibrationParam = (stage, param, value) => {
    setEquilibrationParams((prev) => ({
      ...prev,
      [stage]: {
        ...prev[stage],
        [param]: value,
      },
    }))
  }

  // Build equilibration settings for submission
  const buildEquilibrationSettings = () => {
    return buildEquilibrationSettingsPayload({
      selectedStages,
      stageConfig,
      stageDurations,
      stageDefaults,
      equilibrationParams,
    })
  }

  const timelineStageConfig = useMemo(() => {
    const config = {}
    Object.entries(stageConfig).forEach(([stage, cfg]) => {
      const ps = stageDurations[stage]?.ps || 0
      const isVirtualSelector = isVirtualSelectorStage(stageConfig, stage)
      config[stage] = {
        ...cfg,
        // Minimize is step-based (no ps duration) — assign a small nominal
        // duration so ProtocolTimeline renders a visible segment.
        duration_ps: isVirtualSelector ? 0 : (ps > 0 ? ps : (cfg.type === 'minimize' ? 1 : 0)),
      }
    })
    return config
  }, [stageConfig, stageDurations])

  return {
    selectedStages,
    setSelectedStages,
    stageConfig,
    stageDefaults,
    stageDurations,
    setStageDurations,
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
    // Equilibration stage parameters
    equilibrationParams,
    updateEquilibrationParam,
    buildEquilibrationSettings,
  }
}
