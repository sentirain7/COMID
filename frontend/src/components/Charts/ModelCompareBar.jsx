import { useMemo } from 'react'

/**
 * XGBoost vs RandomForest comparison bars (original-scale holdout RMSE, mean ± std).
 *
 * Lower RMSE is better — bar length is proportional to rmse_mean, with the ±sample
 * standard deviation (error bar) overlaid on top. The winner (lowest mean) is
 * highlighted with ★. Same lightweight CSS bar pattern as FeatureImportanceChart,
 * without recharts.
 */
const MODEL_LABELS = {
  xgboost: 'XGBoost',
  random_forest: 'RandomForest',
}

export default function ModelCompareBar({ models, winner }) {
  const rows = useMemo(() => {
    if (!models) return []
    return Object.entries(models).map(([key, m]) => ({
      key,
      label: MODEL_LABELS[key] || key,
      mean: m.rmse_mean,
      std: m.rmse_std || 0,
      nRepeat: m.per_repeat?.length || 0,
    }))
  }, [models])

  if (!rows.length) return <p className="text-slate-400 text-sm">No evaluation data.</p>

  // Bars and error bars on the same scale — max (mean + std) is 100%.
  const maxVal = Math.max(...rows.map((r) => r.mean + r.std), 1e-9)

  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const isWinner = r.key === winner
        const meanPct = (r.mean / maxVal) * 100
        const loPct = (Math.max(r.mean - r.std, 0) / maxVal) * 100
        const hiPct = (Math.min(r.mean + r.std, maxVal) / maxVal) * 100
        return (
          <div key={r.key} className="flex items-center gap-2 text-xs">
            <span
              className={`w-28 truncate text-right ${
                isWinner ? 'text-emerald-300 font-semibold' : 'text-slate-300'
              }`}
              title={r.label}
            >
              {isWinner ? '★ ' : ''}
              {r.label}
            </span>
            <div className="relative flex-1 h-5 bg-slate-800 rounded overflow-hidden">
              <div
                className="h-full rounded"
                style={{
                  width: `${meanPct}%`,
                  backgroundColor: isWinner
                    ? 'rgba(16,185,129,0.65)'
                    : 'rgba(59,130,246,0.55)',
                }}
              />
              {r.std > 0 && (
                <div
                  className="absolute top-0 bottom-0 border-l border-r border-slate-300/70"
                  style={{ left: `${loPct}%`, width: `${Math.max(hiPct - loPct, 0.5)}%` }}
                  title={`± ${r.std.toFixed(4)} (n=${r.nRepeat})`}
                />
              )}
            </div>
            <span className="w-32 text-right text-slate-400 tabular-nums">
              {r.mean.toFixed(4)}
              <span className="text-slate-500"> ± {r.std.toFixed(4)}</span>
            </span>
          </div>
        )
      })}
      <p className="text-[10px] text-slate-500">
        Bar = mean holdout RMSE (lower is better), white band = ± sample std dev
      </p>
    </div>
  )
}
