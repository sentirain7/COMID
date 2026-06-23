import clsx from 'clsx'

/**
 * ProgressBar - Unified progress display component
 *
 * @param {number} progress - Progress percentage (0-100)
 * @param {number} currentStep - Current step number (optional)
 * @param {number} totalSteps - Total steps count (optional)
 * @param {boolean} showText - Show progress text (default: true)
 * @param {string} size - Bar size: 'sm', 'md', 'lg' (default: 'md')
 * @param {string} color - Bar color: 'blue', 'green', 'yellow', 'red' (default: 'blue')
 */
export function ProgressBar({
  progress = 0,
  currentStep,
  totalSteps,
  showText = true,
  size = 'md',
  color = 'blue',
}) {
  const percentage = Math.min(100, Math.max(0, progress))

  const sizeClasses = {
    sm: 'h-1',
    md: 'h-2',
    lg: 'h-3',
  }

  const colorClasses = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
    red: 'bg-red-500',
  }

  const widthStyles = {
    sm: 'w-16',
    md: 'w-24',
    lg: 'w-32',
  }

  return (
    <div className="flex items-center gap-2">
      <div
        className={clsx(
          'bg-slate-700 rounded-full overflow-hidden',
          sizeClasses[size],
          widthStyles[size]
        )}
      >
        <div
          className={clsx(
            'h-full transition-all duration-300',
            colorClasses[color]
          )}
          style={{ width: `${percentage}%` }}
        />
      </div>
      {showText && (
        <span className="text-sm text-slate-400">
          {totalSteps && totalSteps > 0 ? (
            <>
              {(currentStep ?? 0).toLocaleString()} / {totalSteps.toLocaleString()}{' '}
              <span className="text-slate-500">({percentage.toFixed(1)}%)</span>
            </>
          ) : (
            `${percentage.toFixed(1)}%`
          )}
        </span>
      )}
    </div>
  )
}

/**
 * ProgressBarCompact - Minimal progress bar without text
 */
export function ProgressBarCompact({ progress = 0, size = 'sm', color = 'blue' }) {
  return (
    <ProgressBar
      progress={progress}
      showText={false}
      size={size}
      color={color}
    />
  )
}

export default ProgressBar
