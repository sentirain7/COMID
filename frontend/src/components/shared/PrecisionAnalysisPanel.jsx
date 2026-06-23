/**
 * Precision Analysis Panel — E_inter CPU rerun recommendation display
 *
 * Shows different UI based on recommendation level:
 * - required: Warning alert, toggle locked ON
 * - recommended: Info alert, toggle with recommendation
 * - optional: Collapsed accordion
 * - none: Hidden
 */
import { useEffect, useState } from 'react'
import clsx from 'clsx'

const LEVEL_CONFIG = {
  required: {
    bgClass: 'bg-amber-500/10 border-amber-500/40',
    titleClass: 'text-amber-300',
    icon: '⚠️',
    title: 'Precise E_inter analysis required',
  },
  recommended: {
    bgClass: 'bg-cyan-500/10 border-cyan-500/40',
    titleClass: 'text-cyan-300',
    icon: 'ℹ️',
    title: 'Precise E_inter analysis recommended',
  },
  optional: {
    bgClass: 'bg-slate-700/40 border-slate-600',
    titleClass: 'text-slate-300',
    icon: '⚙️',
    title: 'Precise analysis (optional)',
  },
}

const REASON_DESCRIPTIONS = {
  long_range_metric_selected: 'A long-range-dependent metric was selected.',
  layered_water_ion_polar: 'For layered structures containing water/ions, long-range Coulomb is important.',
  layered_2plus_layers: 'Precise analysis is recommended for layered structures with 2 or more layers.',
  binder_with_additive: 'For a binder containing an additive, precise interaction analysis is useful.',
  binder_without_additive: 'Precise analysis can also be selected for a plain SARA binder.',
}

function getReasonDescription(reasonCodes) {
  if (!reasonCodes || reasonCodes.length === 0) return null
  const code = reasonCodes[0]
  return REASON_DESCRIPTIONS[code] || `Analysis reason: ${reasonCodes.join(', ')}`
}

export function PrecisionAnalysisPanel({
  recommendation,
  onChange,
  className,
  compact = false,
}) {
  const {
    level,
    estimated_cpu_cost_minutes: costMinutes = 0,
    reason_codes: reasonCodes = [],
    affected_metrics: affectedMetrics = [],
    default_enabled: defaultEnabled = false,
  } = recommendation || {}

  // Local toggle state
  const [enabled, setEnabled] = useState(defaultEnabled || level === 'required')

  // Sync with recommendation changes
  useEffect(() => {
    const newEnabled = level === 'required' ? true : (defaultEnabled ?? false)
    setEnabled(newEnabled)
  }, [level, defaultEnabled])

  // Notify parent of changes
  useEffect(() => {
    onChange?.(enabled)
  }, [enabled, onChange])

  const handleToggle = () => {
    if (level === 'required') return // Locked
    setEnabled((prev) => !prev)
  }

  // Hidden for 'none' level or no recommendation
  if (!level || level === 'none') return null

  const config = LEVEL_CONFIG[level] || LEVEL_CONFIG.optional
  const reasonDesc = getReasonDescription(reasonCodes)
  const isLocked = level === 'required'

  // Compact mode: matches Scenario Conditions styling (p-2, space-y-1.5, text-xs)
  const panelPadding = compact ? 'p-2' : 'p-3'
  const panelSpacing = compact ? 'space-y-1.5' : 'space-y-2'
  const compactBg = compact ? 'bg-slate-800/40 border-slate-700' : config.bgClass

  // For optional level, render as collapsible
  if (level === 'optional') {
    return (
      <details className={clsx('rounded-lg border', compactBg, className)}>
        <summary className={clsx('cursor-pointer select-none', compact ? 'p-2 text-xs text-slate-400' : 'p-2 text-sm text-slate-300')}>
          {config.icon} {config.title}
        </summary>
        <div className={clsx('px-2 pb-2', panelSpacing)}>
          {reasonDesc && (
            <p className="text-xs text-slate-400">{reasonDesc}</p>
          )}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={enabled}
              onChange={handleToggle}
              className="w-4 h-4 accent-cyan-500"
            />
            <span className={clsx(compact ? 'text-xs text-slate-300' : 'text-sm text-slate-300')}>
              Enable CPU Rerun (+{costMinutes.toFixed(0)} min)
            </span>
          </label>
          {affectedMetrics.length > 0 && (
            <p className="text-xs text-slate-500">
              Affected metrics: {affectedMetrics.join(', ')}
            </p>
          )}
        </div>
      </details>
    )
  }

  // Required or Recommended level — full panel
  return (
    <div className={clsx('rounded-lg border', panelPadding, panelSpacing, compactBg, className)}>
      {!compact && (
        <div className={clsx('text-sm font-semibold', config.titleClass)}>
          {config.icon} {config.title}
        </div>
      )}

      {reasonDesc && (
        <p className={clsx(compact ? 'text-xs text-slate-400' : 'text-xs text-slate-300')}>{reasonDesc}</p>
      )}

      <div className={clsx('flex items-center', compact ? 'gap-2' : 'gap-3')}>
        {isLocked ? (
          <span className={clsx('rounded border', compact ? 'px-1.5 py-0.5 text-xs bg-amber-500/20 text-amber-300 border-amber-500/40' : 'px-2 py-1 text-xs bg-amber-500/30 text-amber-200 border-amber-500/50')}>
            ON (locked)
          </span>
        ) : (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={enabled}
              onChange={handleToggle}
              className="w-4 h-4 accent-cyan-500"
            />
            <span className={clsx(compact ? 'text-xs text-slate-300' : 'text-sm text-slate-300')}>Enable CPU Rerun</span>
          </label>
        )}
        <span className="text-xs text-slate-400">
          +{costMinutes.toFixed(0)} min estimated
        </span>
      </div>

      {affectedMetrics.length > 0 && (
        <p className="text-xs text-slate-500">
          Affected metrics: {affectedMetrics.join(', ')}
        </p>
      )}
    </div>
  )
}

export default PrecisionAnalysisPanel
