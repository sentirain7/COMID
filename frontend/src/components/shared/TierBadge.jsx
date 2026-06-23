import clsx from 'clsx'

/**
 * Unified tier badge component for run tier display.
 * Single source of truth for tier styling across the app.
 */

const tierStyles = {
  screening: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  confirm: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  viscosity: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  validation: 'bg-red-500/20 text-red-400 border-red-500/30',
}

/**
 * TierBadge - Displays simulation run tier with consistent styling
 *
 * @param {string} tier - Tier value (screening, confirm, viscosity, validation)
 * @param {string} size - Badge size: 'sm', 'md' (default: 'md')
 */
export function TierBadge({ tier, size = 'md' }) {
  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs',
    md: 'px-2 py-1 text-xs',
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center rounded font-medium border',
        tierStyles[tier] || tierStyles.screening,
        sizeClasses[size]
      )}
    >
      {tier}
    </span>
  )
}

/**
 * TierBadgeSimple - Uses clsx badge pattern (for compatibility)
 */
export function TierBadgeSimple({ tier }) {
  return (
    <span className={clsx('badge', tierStyles[tier] || tierStyles.screening)}>
      {tier}
    </span>
  )
}

export default TierBadge
