import { getElementColorCss } from '../molecule-viewer/elementColors'

function ElementLegend({ elements }) {
  if (!elements?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {elements.map((symbol) => (
        <div
          key={symbol}
          className="inline-flex items-center gap-1 rounded border border-slate-600 bg-slate-900/60 px-1.5 py-0.5 text-[10px]"
        >
          <span
            className="inline-block h-2 w-2 rounded-sm border border-slate-500"
            style={{ backgroundColor: getElementColorCss(symbol) }}
          />
          <span className="text-slate-300">{symbol}</span>
        </div>
      ))}
    </div>
  )
}

export default ElementLegend
