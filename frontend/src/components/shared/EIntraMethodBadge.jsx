import { getVisibleEIntraMethodDisplay } from '../../lib/eIntraMethod'

export function EIntraMethodBadge({ method, source = null, scope = 'ced' }) {
  if (!method) return null

  const display = getVisibleEIntraMethodDisplay(method)
  const label = scope === 'e_intra' ? 'E_intra basis' : 'CED basis'
  const titleParts = [label, display.label]
  if (source) titleParts.push(source)

  return (
    <span
      className="inline-flex items-center gap-1 rounded border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-300"
      title={titleParts.join(' • ')}
    >
      <span className="text-cyan-400/80">{label}</span>
      <span className="text-cyan-200">{display.shortLabel || display.label}</span>
    </span>
  )
}
