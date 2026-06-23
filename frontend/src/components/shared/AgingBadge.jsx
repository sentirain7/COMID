import clsx from 'clsx'
import { AGING_BADGE_LABELS, AGING_BADGE_STYLES } from '../../lib/constants'

/**
 * AgingBadge - Displays aging state badge with optional artifact status
 *
 * @param {string} agingState - Aging category (non_aging, short_aging, long_aging)
 * @param {boolean} [artifactReady] - P1.5: Whether artifact is ready (optional)
 * @param {string} [sourceId] - P1.5: Shared source ID for tooltip (optional)
 * @param {boolean} [showArtifactIcon=false] - P1.5: Show ready/missing icon (optional)
 *
 * Backward compatible: existing usage with only agingState continues to work.
 */
function AgingBadge({ agingState, artifactReady, sourceId, showArtifactIcon = false }) {
  if (!agingState) return null

  const baseClasses = clsx(
    'badge text-xs',
    AGING_BADGE_STYLES[agingState] || 'bg-gray-500/20 text-gray-400'
  )
  const label = AGING_BADGE_LABELS[agingState] || agingState

  // Backward compatible: if artifactReady is not provided, render original style
  if (artifactReady === undefined || !showArtifactIcon) {
    return <span className={baseClasses}>{label}</span>
  }

  // P1.5: Enhanced rendering with artifact status icon
  const icon = artifactReady ? '✓' : '✗'
  const iconColor = artifactReady ? 'text-green-400' : 'text-amber-400'
  const title = sourceId
    ? `Source: ${sourceId} (${artifactReady ? 'ready' : 'missing'})`
    : artifactReady
      ? 'Artifact ready'
      : 'Artifact missing'

  return (
    <span className={baseClasses} title={title}>
      {label}
      <span className={clsx('ml-1', iconColor)}>{icon}</span>
    </span>
  )
}

export default AgingBadge
