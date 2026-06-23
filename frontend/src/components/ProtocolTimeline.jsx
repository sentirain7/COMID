import { useMemo } from 'react'
import { getFallbackStageDefinition } from '../lib/protocolStages'

function formatTimelineCondition(condition, targetTempK, targetPressAtm) {
  if (!condition || condition.temperature_mode === 'none') return null
  const { temperature_mode, fixed_temperature_K, uses_target_pressure, n_cycles } = condition

  if (temperature_mode === 'fixed')
    return `${fixed_temperature_K} K`
  if (temperature_mode === 'ramp_from')
    return `${condition.temp_start_K ?? '?'} → ${fixed_temperature_K} K`
  if (temperature_mode === 'ramp')
    return `${targetTempK} ↔ ${fixed_temperature_K} K × ${n_cycles}`
  let label = `${targetTempK} K`
  if (uses_target_pressure) label += ` · ${targetPressAtm} atm`
  return label
}

function ProtocolTimeline({
  selectedStages,
  stageConfig,
  legendPosition = 'bottom',
  compact = false,
  targetTemperatureK,
  targetPressureAtm,
}) {
  const timeline = useMemo(() => {
    let cumTime = 0
    const segments = []
    const orderedStages = Object.entries(stageConfig).sort(([, left], [, right]) => {
      const leftOrder = left?.orderIndex ?? Number.MAX_SAFE_INTEGER
      const rightOrder = right?.orderIndex ?? Number.MAX_SAFE_INTEGER
      return leftOrder - rightOrder
    })

    orderedStages.forEach(([stage, cfg]) => {
      if (!selectedStages[stage]) return
      if (!cfg || cfg.disabled) return
      if (cfg.uiMetadata?.virtualSelector) return
      const fallback = getFallbackStageDefinition(stage) || {}
      const durationPs = Number(cfg.duration_ps ?? 0)

      const conditionLabel = cfg.condition && targetTemperatureK != null
        ? formatTimelineCondition(cfg.condition, targetTemperatureK, targetPressureAtm ?? 1)
        : null

      segments.push({
        stage,
        name: cfg.name,
        shortName: cfg.shortName || fallback.shortName || stage,
        start: cumTime,
        duration: durationPs,
        end: cumTime + durationPs,
        color: cfg.color || fallback.color || '#64748B',
        conditionLabel,
      })
      cumTime += durationPs
    })

    return { segments, totalTime: cumTime }
  }, [selectedStages, stageConfig, targetPressureAtm, targetTemperatureK])

  const formatTime = (ps) => {
    if (ps >= 1000) {
      return `${(ps / 1000).toFixed(1)} ns`
    }
    return `${ps} ps`
  }

  if (timeline.segments.length === 0) {
    return (
      <div className={compact ? 'bg-slate-800 rounded-lg px-2 py-1' : 'bg-slate-800 rounded-lg px-2.5 py-1.5'}>
        <div className={compact ? 'h-5 flex items-center justify-center text-slate-500 text-[11px]' : 'h-6 flex items-center justify-center text-slate-500 text-xs'}>
          No stages selected
        </div>
      </div>
    )
  }

  return (
    <div className={compact ? 'bg-slate-800 rounded-lg px-2 py-1' : 'bg-slate-800 rounded-lg px-2.5 py-1.5'}>
      {/* Timeline bar */}
      <div className={compact ? 'h-5 flex rounded overflow-hidden mb-0.5' : 'h-6 flex rounded overflow-hidden mb-1'}>
        {timeline.segments.map((seg) => {
          const widthPercent = timeline.totalTime > 0
            ? (seg.duration / timeline.totalTime) * 100
            : 0

          return (
            <div
              key={seg.stage}
              className="relative flex items-center justify-center text-xs text-white font-medium transition-all"
              style={{
                width: `${widthPercent}%`,
                backgroundColor: seg.color,
                minWidth: seg.duration > 0 ? '32px' : '0px',
              }}
              title={`${seg.name}: ${formatTime(seg.duration)}${seg.conditionLabel ? ` · ${seg.conditionLabel}` : ''}`}
            >
              {widthPercent >= 10 && seg.shortName}
            </div>
          )
        })}
      </div>

      {legendPosition === 'inline' ? (
        <div className={compact ? 'flex items-center justify-between gap-1.5 text-[11px] text-slate-500' : 'flex items-center justify-between gap-2 text-xs text-slate-500'}>
          <div className={compact ? 'flex items-center gap-1.5 shrink-0' : 'flex items-center gap-2 shrink-0'}>
            <span>0 ps</span>
            <span>{formatTime(timeline.totalTime)}</span>
          </div>
          <div
            className="min-w-0 flex-1 overflow-x-auto [&::-webkit-scrollbar]:hidden"
            style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
          >
            <div className={compact ? 'flex flex-nowrap gap-1 justify-end whitespace-nowrap pl-1.5' : 'flex flex-nowrap gap-1.5 justify-end whitespace-nowrap pl-2'}>
              {timeline.segments.map((seg) => (
                <div
                  key={seg.stage}
                  className={compact ? 'flex items-center gap-0.5 text-[10px] text-slate-400' : 'flex items-center gap-1 text-[11px] text-slate-400'}
                >
                  <div
                    className={compact ? 'w-1.5 h-1.5 rounded-sm' : 'w-2 h-2 rounded-sm'}
                    style={{ backgroundColor: seg.color }}
                  />
                  <span>{seg.shortName}</span>
                  <span className="text-slate-500">({formatTime(seg.duration)})</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Time axis labels */}
          <div className="flex justify-between text-xs text-slate-500">
            <span>0 ps</span>
            <span>{formatTime(timeline.totalTime)}</span>
          </div>

          {/* Stage legend */}
          <div className="mt-2 flex flex-wrap gap-2">
            {timeline.segments.map((seg) => (
              <div
                key={seg.stage}
                className="flex items-center gap-1.5 text-xs text-slate-400"
              >
                <div
                  className="w-2.5 h-2.5 rounded-sm"
                  style={{ backgroundColor: seg.color }}
                />
                <span>{seg.shortName}</span>
                <span className="text-slate-500">({formatTime(seg.duration)})</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default ProtocolTimeline
