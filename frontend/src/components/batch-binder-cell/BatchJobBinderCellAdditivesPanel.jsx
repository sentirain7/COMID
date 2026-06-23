import { useState, useRef } from 'react'
import clsx from 'clsx'
import { formatNumber } from '../../lib/formatters'
import { getAdditiveDisplayLabel } from '../../lib/additiveLabel'
import { getMoleculeStructure } from '../../api/client'
import { SimpleViewer } from '../MoleculeViewer'
import { RefreshCw } from 'lucide-react'
import { useEffect } from 'react'

function AdditiveHoverPreview({ molId, anchorRect }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

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

  const style = {}
  if (anchorRect) {
    style.position = 'fixed'
    style.left = Math.max(8, anchorRect.left + anchorRect.width / 2 - 100)
    style.bottom = window.innerHeight - anchorRect.top + 6
    style.zIndex = 9999
  }

  return (
    <div style={style} className="w-[200px] h-[180px] bg-slate-800 border border-slate-600 rounded-lg shadow-xl overflow-hidden">
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

function BatchJobBinderCellAdditivesPanel({
  additiveTypeOptions,
  selectedAdditiveTypes,
  toggleAdditiveType,
  chipButtonClass,
  additiveSummary,
  additiveCatalog,
  setAdditiveCounts,
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
    <div className="text-sm text-slate-300 flex flex-col md:col-span-2">
      <div className="text-sm font-semibold mb-1">Additives</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1 flex flex-col">
        {additiveTypeOptions.length > 0 ? (
          <div className="flex flex-wrap gap-1.5 items-start">
            <button
              key="none"
              type="button"
              onClick={() => toggleAdditiveType('none')}
              className={chipButtonClass(selectedAdditiveTypes.includes('none'))}
            >
              None
            </button>
            {additiveTypeOptions.map((additiveType) => {
              const entry = additiveCatalog[additiveType] || {}
              const blocked = entry.is_submittable === false
              const title = blocked
                ? `${additiveType}\n⚠ ${entry.blocked_reason || 'blocked'}`
                : additiveType
              return (
                <button
                  key={additiveType}
                  type="button"
                  onClick={() => !blocked && toggleAdditiveType(additiveType)}
                  disabled={blocked}
                  onMouseEnter={(e) => handleMouseEnter(additiveType, e)}
                  onMouseLeave={handleMouseLeave}
                  className={clsx(
                    chipButtonClass(selectedAdditiveTypes.includes(additiveType)),
                    blocked && '!opacity-40 !cursor-not-allowed',
                  )}
                  aria-pressed={selectedAdditiveTypes.includes(additiveType)}
                  title={title}
                >
                  {getAdditiveDisplayLabel(additiveType, additiveCatalog)}
                </button>
              )
            })}
          </div>
        ) : (
          <div className="text-xs text-slate-500">No additives available</div>
        )}
        {selectedAdditiveTypes.length > 0 && (
          <div className="mt-3 border-t border-slate-700 pt-3 space-y-2">
            <div
              className={`text-xs text-slate-400 grid ${additiveSummaryGrid} gap-2 pb-1 border-b border-slate-700`}
            >
              <span>Additive</span>
              <span className="text-right">Count</span>
              <span className="text-right">MW</span>
              <span className="text-right">Weight</span>
              <span className="text-right">%</span>
            </div>
            {additiveSummary.systemRows.map((system) => (
              <div
                key={system.key}
                className={`text-xs grid ${additiveSummaryGrid} gap-2`}
              >
                <span className={system.systemKey === additiveSummary.referenceSystemKey ? 'text-cyan-300' : 'text-slate-300'}>
                  {system.systemKey}
                </span>
                <span />
                <span />
                <span className="text-right text-slate-300">{formatNumber(system.binderWeight)}</span>
                <span className="text-right text-amber-300">{formatNumber(system.totalConcentrationPct)}%</span>
              </div>
            ))}

            <div className="space-y-2 border-t border-slate-700 pt-2">
              {additiveSummary.rows.map((row) => (
                <div
                  key={row.additiveType}
                  className={`grid ${additiveSummaryGrid} gap-2 items-center text-xs`}
                >
                  <span
                    className="text-slate-300 truncate cursor-default"
                    title={row.displayName ? `${row.displayName} (${row.additiveType})` : getAdditiveDisplayLabel(row.additiveType, additiveCatalog)}
                    onMouseEnter={(e) => handleMouseEnter(row.additiveType, e)}
                    onMouseLeave={handleMouseLeave}
                  >
                    {getAdditiveDisplayLabel(row.additiveType, additiveCatalog)}
                  </span>
                  <input
                    type="number"
                    min="0"
                    className="input w-12 justify-self-end py-0.5 px-1 text-xs text-right"
                    value={row.moleculeCount}
                    onChange={(e) => {
                      const value = Math.max(0, Number(e.target.value || 0))
                      setAdditiveCounts((prev) => ({ ...prev, [row.additiveType]: value }))
                    }}
                  />
                  <span className="text-slate-400 text-right">{formatNumber(row.molecularWeight)}</span>
                  <span className="text-slate-400 text-right">{formatNumber(row.weight)}</span>
                  <span />
                </div>
              ))}
              {additiveSummary.rows.length === 0 && (
                <div className="text-xs text-slate-500">
                  No additive components selected. Concentrations are calculated as 0.0%.
                </div>
              )}
              {additiveSummary.rows.length > 0 && (
                <div
                  className={`grid ${additiveSummaryGrid} gap-2 items-center text-xs`}
                >
                  <span className="text-slate-500 font-medium">Additives</span>
                  <span />
                  <span />
                  <span className="text-right text-slate-500">{formatNumber(additiveSummary.totalAdditiveWeight)}</span>
                  <span />
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {hoverMolId && hoverRect && (
        <AdditiveHoverPreview molId={hoverMolId} anchorRect={hoverRect} />
      )}
    </div>
  )
}

export default BatchJobBinderCellAdditivesPanel
