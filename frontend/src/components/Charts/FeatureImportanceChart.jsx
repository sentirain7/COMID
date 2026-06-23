import { useMemo } from 'react'

/**
 * Horizontal bar chart showing top-K feature importances.
 */
export default function FeatureImportanceChart({ data, loading, error }) {
  const features = useMemo(() => {
    if (!data?.features?.length) return []
    return data.features
  }, [data])

  if (loading) return <p className="text-slate-400 text-sm">Loading feature importance...</p>
  if (error) return <p className="text-amber-300 text-sm">{error}</p>
  if (!features.length) return <p className="text-slate-400 text-sm">No feature importance data.</p>

  const maxImp = Math.max(...features.map((f) => f.importance), 1e-9)

  return (
    <div className="space-y-1">
      {data.feature_set_version && (
        <p className="text-xs text-slate-500 mb-2">Feature set: {data.feature_set_version}</p>
      )}
      {features.map((f) => {
        const pct = (f.importance / maxImp) * 100
        const opacity = 0.3 + (f.importance / maxImp) * 0.7
        return (
          <div key={f.name} className="flex items-center gap-2 text-xs">
            <span className="w-40 text-slate-300 truncate text-right font-mono" title={f.name}>
              {f.name}
            </span>
            <div className="flex-1 h-4 bg-slate-800 rounded overflow-hidden">
              <div
                className="h-full rounded"
                style={{
                  width: `${pct}%`,
                  backgroundColor: `rgba(59,130,246,${opacity})`,
                }}
              />
            </div>
            <span className="w-12 text-right text-slate-400 tabular-nums">
              {f.importance.toFixed(3)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
