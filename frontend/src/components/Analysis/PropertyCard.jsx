import { Star, TrendingUp, TrendingDown, Zap } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import { getAnalysisAdditiveColor } from '../../lib/colorPresets'
import useThemeVersion from '../../hooks/useThemeVersion'
// Property Card component
function PropertyCard({ node, baseMetrics, isRecommended }) {
  useThemeVersion('analysis')
  if (!node) return null

  const metrics = [
    { key: 'density', label: 'Density (ρ)', unit: 'g/cm3', precision: 3 },
    { key: 'ced', label: 'CED', unit: 'MJ/m³', precision: 1 },
    { key: 'viscosity', label: 'Viscosity (η)', unit: 'mPa·s', precision: 0 },
    { key: 'adhesion', label: 'Adhesion', unit: 'mJ/m²', precision: 1 },
  ]

  const typeColor = getAnalysisAdditiveColor(node.type)

  return (
    <div
      className="rounded-lg p-4"
      style={{
        backgroundColor: ANALYSIS_BG.card,
        border: `1px solid ${isRecommended ? '#f59e0b' : ANALYSIS_BG.border}`,
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="font-medium" style={{ color: ANALYSIS_BG.text }}>{node.label}</h4>
            {isRecommended && <Star className="w-4 h-4 text-amber-400" fill="#fbbf24" />}
          </div>
          <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
            {node.nodes ? `${node.nodes.length} compositions` : `${node.experiments} experiments`}
          </span>
        </div>
        <span
          className="px-2 py-1 rounded text-xs font-medium"
          style={{ backgroundColor: `${typeColor}20`, color: typeColor }}
        >
          {node.type}
        </span>
      </div>

      {isRecommended && (
        <div className="mb-3 p-2 bg-amber-500/10 rounded text-xs text-amber-400 flex items-center gap-2">
          <Zap className="w-3 h-3" />
          Recommended: Highest CED improvement
        </div>
      )}

      <div className="space-y-3">
        {metrics.map(({ key, label, unit, precision }) => {
          const value = node.metrics[key]
          const baseValue = baseMetrics[key]
          const delta = ((value / baseValue - 1) * 100)
          const isPositive = delta >= 0

          return (
            <div key={key} className="flex items-center justify-between">
              <span className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>{label}</span>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium" style={{ color: ANALYSIS_BG.text }}>{value.toFixed(precision)} {unit}</span>
                {node.type !== 'base' && (
                  <span className={`flex items-center text-xs ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
                    {isPositive ? <TrendingUp className="w-3 h-3 mr-0.5" /> : <TrendingDown className="w-3 h-3 mr-0.5" />}
                    {isPositive ? '+' : ''}{delta.toFixed(1)}%
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
export default PropertyCard
