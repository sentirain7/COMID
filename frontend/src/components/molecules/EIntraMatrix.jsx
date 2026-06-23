import { FALLBACK_TEMPERATURES_K } from '../batch-binder-cell/config'
import { getVisibleEIntraMethodDisplay } from '../../lib/eIntraMethod'

/**
 * 2×6 matrix showing E_intra computation status per temperature.
 *
 * Each cell = one temperature from the SSOT set (213–433 K, 20 K step).
 * Green = computed, red = missing, gray = no coverage data.
 *
 * Props:
 *   coverage - e_intra_coverage object from the molecules API:
 *     { computed_count, required_count, needs_calc,
 *       latest_values_by_temperature?, missing_temperatures_k? }
 */
const TEMPS = FALLBACK_TEMPERATURES_K  // [213, 233, …, 433] — 12 items

export function EIntraMatrix({ coverage }) {
  if (!coverage) {
    return (
      <div className="grid grid-cols-6 gap-px" title="E_intra: N/A">
        {TEMPS.map((t) => (
          <div key={t} className="w-2 h-2 rounded-sm bg-slate-700" title={`${t}K`} />
        ))}
      </div>
    )
  }

  const computed = coverage.latest_values_by_temperature || {}
  // Keys from server may be string or number — normalize to number set
  const computedSet = new Set(Object.keys(computed).map(Number))

  // PR 2 (Method 1a SSOT, Codex Round 6): expose the coverage method in
  // the tooltip so the matrix is unambiguous when Method 1 / 1a coexist.
  const { computed_count = 0, required_count = TEMPS.length, method } = coverage
  const methodDisplay = getVisibleEIntraMethodDisplay(method)
  const methodLabel = methodDisplay.label
  const summary = `E_intra: ${computed_count}/${required_count} [method: ${methodLabel}]`

  return (
    <div className="grid grid-cols-6 gap-px" title={summary}>
      {TEMPS.map((t) => {
        const done = computedSet.has(t)
        return (
          <div
            key={t}
            className={
              done
                ? 'w-2 h-2 rounded-sm bg-emerald-400'
                : 'w-2 h-2 rounded-sm bg-red-400/70'
            }
            title={`${t}K${done ? ' ✓' : ''} [method: ${methodLabel}]`}
          />
        )
      })}
    </div>
  )
}
