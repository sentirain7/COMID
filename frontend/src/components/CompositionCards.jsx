import { Eye } from 'lucide-react'
import clsx from 'clsx'
import { SARA_TEXT_COLORS } from '../lib/constants'

function resolveTitleDisplay(title, subtitle) {
  const normalizedTitle = String(title ?? '').trim() || '-'
  const normalizedSubtitle = typeof subtitle === 'string' ? subtitle.trim() : ''

  if (normalizedSubtitle) {
    return {
      line1: normalizedTitle,
      line2: normalizedSubtitle,
      secondaryMuted: true,
    }
  }

  return {
    line1: normalizedTitle,
    line2: '',
    secondaryMuted: true,
  }
}

function CompositionCards({
  cards,
  editable = false,
  onCountChange,
  onPreview,
  selectable = false,
  selectedKey = null,
  onSelect,
  selectedClassName = 'border-blue-500/60 bg-blue-500/10',
  countLabel = 'Count',
}) {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 lg:grid-cols-8 gap-1.5 auto-rows-fr">
      {cards.map((card) => {
        const isAdditive = card.kind === 'additive'
        const titleDisplay = resolveTitleDisplay(card.title, card.subtitle)
        const isSelected = selectable && selectedKey === card.key
        const canSelect = selectable && typeof onSelect === 'function'
        const resolvedCountLabel = card.countLabel || countLabel
        const resolvedCountDisplay = card.countDisplay ?? card.count
        const showSubtitle = Boolean(titleDisplay.line2)

        return (
          <div
            key={card.key}
            className={clsx(
              'rounded border border-slate-600 bg-slate-700/40 px-1 py-1 text-xs text-slate-300 transition-colors min-w-0',
              'flex flex-col gap-0.5 text-left',
              canSelect && 'cursor-pointer hover:bg-slate-700',
              isSelected && selectedClassName
            )}
            onClick={canSelect ? () => onSelect(card) : undefined}
            onKeyDown={
              canSelect
                ? (event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect(card)
                    }
                  }
                : undefined
            }
            role={canSelect ? 'button' : undefined}
            tabIndex={canSelect ? 0 : undefined}
            aria-pressed={canSelect ? isSelected : undefined}
            title={canSelect ? card.subtitle || card.title : undefined}
          >
            <div className="flex items-center justify-between gap-1 min-w-0">
              <div className="min-w-0 flex-1 space-y-0.5">
                <span
                  className={clsx(
                    'block text-[11px] font-medium leading-tight truncate',
                    isAdditive ? 'text-cyan-300' : (SARA_TEXT_COLORS[card.saraType] || 'text-white'),
                  )}
                  title={card.title}
                >
                  {titleDisplay.line1}
                </span>
                {showSubtitle && (
                  <span
                    className={clsx(
                      'block text-[10px] leading-tight truncate',
                      titleDisplay.secondaryMuted
                        ? 'text-slate-500'
                        : (isAdditive ? 'text-cyan-300' : (SARA_TEXT_COLORS[card.saraType] || 'text-white'))
                    )}
                    title={titleDisplay.line2}
                  >
                    {titleDisplay.line2}
                  </span>
                )}
              </div>
              {onPreview && (
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onPreview(card)
                  }}
                  className="shrink-0 p-0.5 rounded hover:bg-slate-600 text-slate-400 hover:text-white"
                  title="View 3D structure"
                  aria-label={`View ${card.title} structure`}
                >
                  <Eye className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            <div className="flex items-center justify-between gap-1">
              <span className="text-[10px] text-slate-500 truncate">{resolvedCountLabel}</span>
              {editable && !isAdditive ? (
                <input
                  type="number"
                  value={card.count}
                  onChange={(e) => onCountChange?.(card.index, parseInt(e.target.value) || 0)}
                  onClick={(event) => event.stopPropagation()}
                  className="w-11 h-6 text-center input py-0 text-xs"
                  min="0"
                />
              ) : (
                <span className="text-slate-100 text-xs font-medium truncate">{resolvedCountDisplay}</span>
              )}
            </div>
          </div>
        )
      })}
      {cards.length === 0 && (
        <div className="col-span-full text-xs text-slate-500">
          No molecules loaded.
        </div>
      )}
    </div>
  )
}

export default CompositionCards
