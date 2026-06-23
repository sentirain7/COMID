import { useState, useEffect, useRef } from 'react'
import clsx from 'clsx'
import { formatNumber } from '../../lib/formatters'
import { getAdditiveDisplayLabel } from '../../lib/additiveLabel'
import { getMoleculeStructure } from '../../api/client'
import { SimpleViewer } from '../MoleculeViewer'
import { RefreshCw } from 'lucide-react'

function AdditiveHoverPreview({ molId, anchorRect }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const ref = useRef(null)

  useEffect(() => {
    let mounted = true
    setLoading(true)
    getMoleculeStructure(molId)
      .then((res) => {
        if (mounted) setData({ xyz: res?.xyz || '', bonds: res?.bonds || [] })
      })
      .catch(() => {
        if (mounted) setData(null)
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => { mounted = false }
  }, [molId])

  // Position: above the anchor, centered horizontally
  const style = {}
  if (anchorRect) {
    style.position = 'fixed'
    style.left = Math.max(8, anchorRect.left + anchorRect.width / 2 - 100)
    style.bottom = window.innerHeight - anchorRect.top + 6
    style.zIndex = 9999
  }

  return (
    <div ref={ref} style={style} className="w-[200px] h-[180px] bg-slate-800 border border-slate-600 rounded-lg shadow-xl overflow-hidden">
      {loading && (
        <div className="flex items-center justify-center h-full">
          <RefreshCw className="w-5 h-5 text-blue-400 animate-spin" />
        </div>
      )}
      {!loading && data?.xyz && (
        <div className="w-full h-full [&>div]:!min-h-0">
          <SimpleViewer xyzData={data.xyz} bonds={data.bonds} fitToFrame fitPadding={1.3} />
        </div>
      )}
      {!loading && !data?.xyz && (
        <div className="flex items-center justify-center h-full text-[10px] text-slate-500">
          No structure
        </div>
      )}
    </div>
  )
}

function BinderAdditivesPanel({
  availableAdditives,
  selectedAdditives,
  handleAdditiveToggle,
  chipButtonClass,
  additiveSummary,
  handleAdditiveCountChange,
  additiveSummaryGrid,
}) {
  const [hoverMolId, setHoverMolId] = useState(null)
  const [hoverRect, setHoverRect] = useState(null)
  const hoverTimerRef = useRef(null)

  const handleMouseEnter = (molId, e) => {
    clearTimeout(hoverTimerRef.current)
    const rect = e.currentTarget.getBoundingClientRect()
    hoverTimerRef.current = setTimeout(() => {
      setHoverMolId(molId)
      setHoverRect(rect)
    }, 350)
  }

  const handleMouseLeave = () => {
    clearTimeout(hoverTimerRef.current)
    setHoverMolId(null)
    setHoverRect(null)
  }

  return (
    <div className="text-sm text-slate-300 flex flex-col">
      <div className="text-sm font-semibold mb-1">Additives</div>
      <div
        className={clsx(
          'rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1 flex flex-col',
          selectedAdditives.length === 0 && 'h-[90px]'
        )}
      >
        {availableAdditives.length > 0 ? (
          <div className="space-y-2 flex-1 min-h-0 overflow-y-auto pr-1">
            <div className="flex flex-wrap gap-1.5">
              <button
                key="none"
                type="button"
                onClick={() => handleAdditiveToggle({ mol_id: '__none__' })}
                className={chipButtonClass(selectedAdditives.length === 0)}
              >
                None
              </button>
              {availableAdditives.map((additive) => {
                const selected = selectedAdditives.find((a) => a.mol_id === additive.mol_id)
                const blocked = additive.is_submittable === false
                const label = getAdditiveDisplayLabel(additive.mol_id, { [additive.mol_id]: additive })
                let title
                if (blocked) {
                  title = `${additive.mol_id}\n⚠ ${additive.blocked_reason || 'blocked'}`
                } else {
                  title = additive.mol_id
                }
                return (
                  <button
                    key={additive.mol_id}
                    type="button"
                    onClick={() => !blocked && handleAdditiveToggle(additive)}
                    disabled={blocked}
                    onMouseEnter={(e) => handleMouseEnter(additive.mol_id, e)}
                    onMouseLeave={handleMouseLeave}
                    className={clsx(
                      chipButtonClass(!!selected),
                      blocked && '!opacity-40 !cursor-not-allowed',
                    )}
                    title={title}
                  >
                    {label}
                  </button>
                )
              })}
            </div>

            <div className="border-t border-slate-700 pt-2 space-y-1.5">
              {selectedAdditives.length === 0 ? (
                <div className="text-xs text-slate-500">No additives selected</div>
              ) : (
                <>
                  <div className={`grid ${additiveSummaryGrid} gap-2 text-[10px] text-slate-500 uppercase tracking-wide`}>
                    <span>Additive</span>
                    <span className="text-right">Count</span>
                    <span className="text-right">MW</span>
                    <span className="text-right">Weight</span>
                    <span className="text-right">%</span>
                  </div>
                  <div className={`grid ${additiveSummaryGrid} gap-2 items-center text-xs`}>
                    <span className="text-slate-500 font-medium">Binder</span>
                    <span className="text-slate-400 text-right">-</span>
                    <span className="text-slate-400 text-right">-</span>
                    <span className="text-right text-slate-500">{formatNumber(additiveSummary.binderWeight, 1)}</span>
                    <span className="text-right text-slate-500">{formatNumber(additiveSummary.binderPct, 2)}%</span>
                  </div>
                  {additiveSummary.rows.map((row) => (
                    <div
                      key={row.molId}
                      className={`grid ${additiveSummaryGrid} gap-2 items-center text-xs`}
                    >
                      <span
                        className="text-slate-300 truncate cursor-default"
                        title={row.name}
                        onMouseEnter={(e) => handleMouseEnter(row.molId, e)}
                        onMouseLeave={handleMouseLeave}
                      >
                        {row.name}
                      </span>
                      <input
                        type="number"
                        min="0"
                        value={row.moleculeCount}
                        onChange={(e) => handleAdditiveCountChange(row.molId, parseInt(e.target.value, 10) || 0)}
                        className="input w-12 justify-self-end py-0.5 px-1 text-xs text-right"
                      />
                      <span className="text-slate-400 text-right">{formatNumber(row.molecularWeight, 1)}</span>
                      <span className="text-slate-400 text-right">{formatNumber(row.weight, 1)}</span>
                      <span className="text-amber-300 text-right">{formatNumber(row.ratioPct, 2)}%</span>
                    </div>
                  ))}
                  <div className={`grid ${additiveSummaryGrid} gap-2 items-center text-xs`}>
                    <span className="text-slate-500 font-medium">Total</span>
                    <span />
                    <span />
                    <span className="text-right text-slate-500">{formatNumber(additiveSummary.totalAdditiveWeight, 1)}</span>
                    <span className="text-right text-slate-500">{formatNumber(additiveSummary.totalConcentrationPct, 2)}%</span>
                  </div>
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-500">No additives available</div>
        )}
      </div>

      {/* Hover preview portal */}
      {hoverMolId && hoverRect && (
        <AdditiveHoverPreview molId={hoverMolId} anchorRect={hoverRect} />
      )}
    </div>
  )
}

export default BinderAdditivesPanel
