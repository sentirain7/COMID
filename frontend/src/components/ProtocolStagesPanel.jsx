import { Minus, Plus, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import { getFallbackStageDefinition, getStageParameterFields } from '../lib/protocolStages'

function formatStageCondition(condition, targetTempK, targetPressAtm) {
  if (!condition || condition.temperature_mode === 'none') return null
  const { temperature_mode, fixed_temperature_K, uses_target_pressure, n_cycles } = condition

  if (temperature_mode === 'fixed')
    return `${fixed_temperature_K} K`
  if (temperature_mode === 'ramp_from')
    return `${condition.temp_start_K ?? '?'} → ${fixed_temperature_K} K`
  if (temperature_mode === 'ramp')
    return `${targetTempK} ↔ ${fixed_temperature_K} K × ${n_cycles}`
  // target
  let label = `${targetTempK} K`
  if (uses_target_pressure) label += ` · ${targetPressAtm} atm`
  return label
}

function ProtocolStagesPanel({
  stageConfig,
  stageDurations,
  selectedStages,
  loading = false,
  compact = false,
  titleClassName,
  onToggleStage,
  onDurationChange,
  onResetDuration,
  isDurationModified,
  viscosityTemps,
  onViscosityTempChange,
  onAddViscosityTemp,
  onRemoveViscosityTemp,
  // Equilibration stage parameters
  equilibrationParams,
  onEquilibrationParamChange,
  // Target temperature/pressure for condition labels
  targetTemperatureK,
  targetPressureAtm,
}) {
  const orderedStages = Object.entries(stageConfig).sort(([, left], [, right]) => {
    const leftOrder = left?.orderIndex ?? Number.MAX_SAFE_INTEGER
    const rightOrder = right?.orderIndex ?? Number.MAX_SAFE_INTEGER
    return leftOrder - rightOrder
  })

  const stageCards = []
  orderedStages.forEach(([stage, cfg]) => {
    const fallback = getFallbackStageDefinition(stage) || {}
    const isSelected = selectedStages[stage]
    const displayName = compact
      ? (cfg.compactDisplayName || fallback.compactDisplayName || cfg.name)
      : cfg.name
    const isVirtualSelector = Boolean(cfg.uiMetadata?.virtualSelector)
    const hasDuration = isSelected && !cfg.disabled && stageDurations[stage] && !isVirtualSelector
    const durationUnit = cfg.type === 'minimize' ? 'steps' : 'ps'
    const durationValue = cfg.type === 'minimize'
      ? stageDurations[stage]?.steps ?? ''
      : stageDurations[stage]?.ps ?? ''
    const stageColor = cfg.color || fallback.color
    const bounds = cfg.bounds || {}
    const durationBounds = bounds.duration_ps || {}
    const temperatureBounds = bounds.temperature_K || {}
    const pressureBounds = bounds.pressure_atm || {}
    const isEquilibration = Boolean(cfg.uiMetadata?.is_equilibration || fallback.uiMetadata?.is_equilibration)
    const parameterFields = getStageParameterFields(stageConfig, stage)

    stageCards.push(
      <div
        key={stage}
        className={clsx(
          compact
            ? 'rounded-md border border-slate-700/60 bg-slate-900/30 p-1 flex flex-col gap-0.5 transition-colors min-w-0'
            : 'rounded-md border border-slate-700/60 bg-slate-900/30 p-1 flex flex-col gap-0.5 transition-colors min-w-0',
          cfg.disabled && 'opacity-50',
          isSelected && !cfg.disabled ? 'border-blue-500/40 bg-blue-500/10' : 'hover:bg-slate-700/30',
        )}
      >
        <label
          className={clsx(
            'flex items-center gap-1.5 min-w-0 cursor-pointer',
            cfg.disabled && 'cursor-not-allowed',
          )}
        >
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleStage(stage)}
            disabled={cfg.required || cfg.disabled}
            className="w-3 h-3 rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
          />
          <span
            className={clsx(
              'text-[11px] font-medium leading-tight whitespace-nowrap truncate',
              cfg.disabled ? 'text-slate-500' : 'text-white',
            )}
            style={!cfg.disabled && stageColor ? { color: stageColor } : undefined}
            title={cfg.name}
          >
            {displayName}
          </span>
          {cfg.disabled && (
            <span className="px-1 py-0.5 text-[9px] bg-slate-700 text-slate-400 rounded">soon</span>
          )}
        </label>

        {/* Condition annotation (temperature/pressure) */}
        {isSelected && !cfg.disabled && cfg.condition && targetTemperatureK != null && (() => {
          const label = formatStageCondition(cfg.condition, targetTemperatureK, targetPressureAtm ?? 1)
          return label ? (
            <div className="text-[9px] text-slate-400 truncate pl-4" title={label}>
              {label}
            </div>
          ) : null
        })()}

        {hasDuration ? (
          <div className="flex flex-col gap-0.5 w-full min-w-0">
            {/* Duration input */}
            <div className="flex items-center gap-1 w-full min-w-0">
              <input
                type="number"
                value={durationValue}
                onChange={(e) => onDurationChange(
                  stage,
                  cfg.type === 'minimize'
                    ? parseInt(e.target.value) || null
                    : parseFloat(e.target.value) || null,
                  durationUnit,
                )}
                className={compact ? 'w-full min-w-0 input text-[10px] h-5 py-0' : 'w-full min-w-0 input text-[11px] h-5 py-0'}
                min={cfg.type === 'minimize' ? 100 : durationBounds.min ?? 10}
                max={cfg.type === 'minimize' ? undefined : durationBounds.max}
                placeholder={durationUnit}
              />
              <span className={compact ? 'text-[9px] text-slate-400' : 'text-[10px] text-slate-400'}>{durationUnit}</span>
              {isDurationModified(stage) && (
                <button
                  type="button"
                  onClick={() => onResetDuration(stage)}
                  className="p-0.5 text-slate-400 hover:text-blue-400"
                  title="Reset to default"
                >
                  <RefreshCw className="w-3 h-3" />
                </button>
              )}
            </div>
            {/* Equilibration stage parameters (temperature, pressure) */}
            {isEquilibration && equilibrationParams && onEquilibrationParamChange && parameterFields.length > 0 && (
              <div className="flex items-center gap-1 w-full min-w-0">
                {parameterFields.map((fieldConfig) => {
                  const fieldBounds = bounds[fieldConfig.field] || (
                    fieldConfig.field === 'temperature_K'
                      ? temperatureBounds
                      : fieldConfig.field === 'pressure_atm'
                        ? pressureBounds
                        : {}
                  )
                  const rawValue = equilibrationParams[stage]?.[fieldConfig.field]
                  const fallbackValue = fieldConfig.field === 'pressure_atm' ? 100 : 500
                  const parseValue = (value) => {
                    if (fieldConfig.parseAs === 'int') {
                      return parseInt(value) || fallbackValue
                    }
                    return parseFloat(value) || fallbackValue
                  }

                  return (
                    <div key={fieldConfig.field} className="flex items-center gap-1">
                    <input
                      type="number"
                      value={rawValue ?? fallbackValue}
                      onChange={(e) => onEquilibrationParamChange(stage, fieldConfig.field, parseValue(e.target.value))}
                      className={compact ? 'w-12 min-w-0 input text-[10px] h-5 py-0' : 'w-14 min-w-0 input text-[11px] h-5 py-0'}
                      min={fieldBounds.min}
                      max={fieldBounds.max}
                      step={fieldConfig.step ?? 1}
                      aria-label={`${cfg.name} ${fieldConfig.label} (${fieldConfig.unit})`}
                      title={`${fieldConfig.label} (${fieldConfig.unit})`}
                    />
                    <span className="text-[9px] text-slate-400">{fieldConfig.unit}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        ) : isVirtualSelector ? (
          <div
            className="text-[10px] text-slate-400"
            title={cfg.uiMetadata?.selectorDescription || 'Uses the selected protocol chain defaults'}
          >
            {cfg.uiMetadata?.selectorDescription || 'Uses selected chain defaults'}
          </div>
        ) : (
          <div className="text-[10px] text-slate-500">—</div>
        )}
      </div>
    )
  })

  return (
    <div className="text-sm text-slate-300 md:col-span-2 flex flex-col">
      <div
        className={
          titleClassName
            ? titleClassName
            : compact
              ? 'text-sm font-semibold mb-0.5 flex items-center gap-2'
              : 'text-sm font-semibold mb-1 flex items-center gap-2'
        }
      >
        Protocol Stages
        {loading && (
          <div className="w-3 h-3 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
        )}
      </div>
      <div className={compact ? 'rounded-lg border border-slate-700 bg-slate-800/40 p-1.5' : 'rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1'}>
        <div className={compact ? 'grid grid-cols-1 sm:grid-cols-3 gap-1 auto-rows-fr' : 'grid grid-cols-2 sm:grid-cols-5 gap-1.5 auto-rows-fr'}>
          {stageCards}

          {selectedStages.viscosity_nemd && (
            <div className="sm:col-span-3 lg:col-span-4 mt-1 p-1.5 bg-slate-700/30 rounded-lg">
              <div className="text-[11px] text-slate-400 mb-1">Viscosity Temps</div>
              <div className="flex flex-wrap gap-1.5 items-center">
                {viscosityTemps.map((temp, index) => (
                  <div key={index} className="flex items-center gap-1">
                    <input
                      type="number"
                      value={temp}
                      onChange={(e) => onViscosityTempChange(index, parseInt(e.target.value) || 298)}
                      className="w-14 input py-0.5 text-[11px]"
                      min="200"
                      max="500"
                    />
                    <span className="text-[10px] text-slate-400">K</span>
                    {viscosityTemps.length > 1 && (
                      <button
                        type="button"
                        onClick={() => onRemoveViscosityTemp(index)}
                        className="p-0.5 text-slate-400 hover:text-red-400"
                      >
                        <Minus className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                ))}
                {viscosityTemps.length < 5 && (
                  <button
                    type="button"
                    onClick={onAddViscosityTemp}
                    className="px-1.5 py-0.5 text-xs bg-slate-700 hover:bg-slate-600 rounded flex items-center gap-1"
                  >
                    <Plus className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ProtocolStagesPanel
