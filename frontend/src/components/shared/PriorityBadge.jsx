import clsx from 'clsx'

/**
 * Unified priority badge component for job priority display.
 */

const priorityStyles = {
  highest: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  low: 'bg-green-500/20 text-green-400 border-green-500/30',
  lowest: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

/**
 * PriorityBadge - Displays job priority with consistent styling
 *
 * @param {string} priority - Priority value (highest, high, medium, low, lowest)
 * @param {string} size - Badge size: 'sm', 'md' (default: 'md')
 */
export function PriorityBadge({ priority, size = 'md' }) {
  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs',
    md: 'px-2 py-1 text-xs',
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center rounded font-medium border',
        priorityStyles[priority] || priorityStyles.medium,
        sizeClasses[size]
      )}
    >
      {priority}
    </span>
  )
}

export default PriorityBadge
