import clsx from 'clsx'

/**
 * MetricStatusBadge - displays model performance status based on the R² value
 *
 * @param {number|null} r2 - R² (coefficient of determination) value
 */
function MetricStatusBadge({ r2 }) {
  const getStatus = (r2Value) => {
    if (r2Value == null) return { label: '-', styles: 'bg-slate-500/20 text-slate-400 border-slate-500/30' }
    if (r2Value >= 0.9) return { label: 'Excellent', styles: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' }
    if (r2Value >= 0.7) return { label: 'Good', styles: 'bg-green-500/20 text-green-400 border-green-500/30' }
    if (r2Value >= 0.5) return { label: 'Moderate', styles: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' }
    return { label: 'Poor', styles: 'bg-red-500/20 text-red-400 border-red-500/30' }
  }

  const { label, styles } = getStatus(r2)

  return (
    <span
      className={clsx(
        'inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium border',
        styles
      )}
    >
      {label}
    </span>
  )
}

export default MetricStatusBadge
