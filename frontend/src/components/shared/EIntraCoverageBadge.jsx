import { getVisibleEIntraMethodDisplay } from '../../lib/eIntraMethod'

// Uniform badge size — matches CategoryBadge / FFRouteBadge for consistent table column widths.
const BADGE_BASE = 'inline-flex items-center justify-center w-24 px-1.5 py-0.5 rounded text-[10px] border overflow-hidden'

export function EIntraCoverageBadge({ coverage }) {
  if (!coverage) {
    return (
      <span className={`${BADGE_BASE} bg-slate-700/30 text-slate-500 border-slate-600`} title="N/A">
        <span className="truncate">N/A</span>
      </span>
    )
  }
  const {
    computed_count = 0,
    required_count = 12,
    needs_calc,
    method,
  } = coverage
  const ratio = `${computed_count}/${required_count}`
  const methodDisplay = getVisibleEIntraMethodDisplay(method)
  const tipMethod = methodDisplay.supported ? methodDisplay.label : 'Deferred/internal method'
  const prefix = methodDisplay.shortLabel ? `E_intra·${methodDisplay.shortLabel.replace('Method ', '')} ` : 'E_intra '
  if (!needs_calc && computed_count >= required_count) {
    return (
      <span
        className={`${BADGE_BASE} bg-emerald-500/15 border-emerald-500/40 text-emerald-400`}
        title={`Done (${ratio}) [method: ${tipMethod}]`}
      >
        <span className="truncate">{prefix}{ratio}</span>
      </span>
    )
  }
  if (computed_count > 0) {
    return (
      <span
        className={`${BADGE_BASE} bg-amber-500/15 border-amber-500/40 text-amber-400`}
        title={`Partial (${ratio}) [method: ${tipMethod}]`}
      >
        <span className="truncate">{prefix}{ratio}</span>
      </span>
    )
  }
  return (
    <span
      className={`${BADGE_BASE} bg-red-500/15 border-red-500/40 text-red-400`}
      title={`Need calc [method: ${tipMethod}]`}
    >
      <span className="truncate">{prefix}0/{required_count}</span>
    </span>
  )
}
