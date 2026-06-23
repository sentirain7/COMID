import { getAdditiveColor, getPointStyle, getGlowStyle } from '../../lib/chartUtils'
import useThemeVersion from '../../hooks/useThemeVersion'

function ScatterPlotBase({
  title,
  showMockLabel = false,
  loading = false,
  additives = [],
  selectedAdditive,
  onAdditiveChange,
  points = [],
  xLabel,
  yLabel,
  xTickLabels = [],
  yTickLabels = [],
  normalizeX,
  normalizeY,
  gridLinesX = false,
  referenceLines = [],
  renderTooltip,
}) {
  useThemeVersion('chart')
  if (loading) {
    return (
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 h-full">
        <h3 className="text-sm font-semibold text-white mb-3">{title}</h3>
        <div className="animate-pulse flex-1 bg-slate-700 rounded h-32" />
      </div>
    )
  }

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 h-full flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">
          {title}
          {showMockLabel && <span className="text-xs text-slate-500 ml-2">(Mock)</span>}
        </h3>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 text-xs">
            <div className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-slate-400 border border-white" />
              <span className="text-slate-500">Recent</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-slate-500 opacity-50" />
              <span className="text-slate-500">Old</span>
            </div>
          </div>
          {additives.length > 0 && onAdditiveChange && (
            <select
              value={selectedAdditive}
              onChange={(e) => onAdditiveChange(e.target.value)}
              className="bg-slate-700 border border-slate-600 text-white text-xs rounded px-2 py-0.5"
            >
              <option value="all">All</option>
              {additives.map((add) => (
                <option key={add} value={add}>{add}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      <div className="relative flex-1 min-h-[120px] ml-20 border-l border-b border-slate-600">
        {/* Y-axis tick labels */}
        <div className="absolute -left-12 top-0 bottom-0 flex flex-col justify-between text-xs text-slate-400 text-right w-11">
          {yTickLabels.map((label, index) => (
            <span key={`${label}-${index}`}>{label}</span>
          ))}
        </div>

        {/* Y-axis label (rotated) */}
        <div className="absolute -left-[76px] top-1/2 -translate-y-1/2 -rotate-90 text-xs text-slate-400 whitespace-nowrap">
          {yLabel}
        </div>

        <div className="absolute inset-0">
          {[25, 50, 75].map((pct) => (
            <div
              key={pct}
              className="absolute w-full border-t border-slate-700 border-dashed"
              style={{ bottom: `${pct}%` }}
            />
          ))}
          {gridLinesX && [25, 50, 75].map((pct) => (
            <div
              key={`v-${pct}`}
              className="absolute h-full border-l border-slate-700 border-dashed"
              style={{ left: `${pct}%` }}
            />
          ))}
        </div>

        {referenceLines.map((line) => (
          <div
            key={line.value}
            className="absolute w-full border-t-2 border-slate-500 border-dashed"
            style={{ bottom: `${normalizeY(line.value)}%` }}
          >
            {line.label && (
              <span className="absolute right-0 -top-3 text-xs text-slate-500">{line.label}</span>
            )}
          </div>
        ))}

        <div className="absolute inset-0">
          {points.map((point, i) => {
            const style = getPointStyle(point)
            const pointColor = getAdditiveColor(point.additive)
            const glowStyle = getGlowStyle(pointColor)
            return (
              <div
                key={point.key ?? i}
                className="absolute group"
                style={{
                  left: `${normalizeX(point.x)}%`,
                  bottom: `${normalizeY(point.y)}%`,
                  transform: 'translate(-50%, 50%)',
                }}
              >
                <div
                  className="w-3 h-3 rounded-full cursor-pointer transition-all hover:scale-150"
                  style={{
                    backgroundColor: pointColor,
                    opacity: style.opacity,
                    border: style.border,
                    boxSizing: 'border-box',
                    ...glowStyle,
                  }}
                />
                {renderTooltip && (
                  <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-slate-900 rounded text-xs whitespace-nowrap z-10">
                    {renderTooltip(point)}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* X-axis tick labels */}
        <div className="absolute left-0 right-0 -bottom-5 flex justify-between text-xs text-slate-400 px-1">
          {xTickLabels.map((label, index) => (
            <span key={`${label}-${index}`}>{label}</span>
          ))}
        </div>
      </div>

      {/* X-axis label */}
      <div className="mt-6 text-center text-xs text-slate-400">
        {xLabel}
      </div>

      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {additives.map((add) => (
          <div key={add} className="flex items-center gap-1">
            <div
              className="w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: getAdditiveColor(add) }}
            />
            <span className="text-slate-500">{add}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ScatterPlotBase
