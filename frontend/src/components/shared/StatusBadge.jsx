import { Clock, Play, CheckCircle, XCircle } from 'lucide-react'
import clsx from 'clsx'

/**
 * Unified status badge component for experiment/job status display.
 * Single source of truth for status styling across the app.
 */

const statusConfig = {
  pending: {
    styles: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    cssClass: 'status-pending',
    icon: Clock,
  },
  draft: {
    styles: 'bg-slate-500/20 text-slate-300 border-slate-500/30',
    cssClass: 'bg-slate-500/20 text-slate-300 border-slate-500/30',
    icon: Clock,
  },
  active: {
    styles: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
    cssClass: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
    icon: Play,
  },
  approved: {
    styles: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    cssClass: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    icon: CheckCircle,
  },
  rejected: {
    styles: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
    cssClass: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
    icon: XCircle,
  },
  queued: {
    styles: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    cssClass: 'status-queued',
    icon: Clock,
  },
  submitted: {
    styles: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    cssClass: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    icon: Clock,
  },
  building: {
    styles: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
    cssClass: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
    icon: Play,
  },
  ready: {
    styles: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    cssClass: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    icon: Clock,
  },
  running: {
    styles: 'bg-green-500/20 text-green-400 border-green-500/30',
    cssClass: 'status-running',
    icon: Play,
  },
  completed: {
    styles: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    cssClass: 'status-completed',
    icon: CheckCircle,
  },
  failed: {
    styles: 'bg-red-500/20 text-red-400 border-red-500/30',
    cssClass: 'status-failed',
    icon: XCircle,
  },
  error: {
    styles: 'bg-red-500/20 text-red-400 border-red-500/30',
    cssClass: 'bg-red-500/20 text-red-400 border-red-500/30',
    icon: XCircle,
  },
  cancelled: {
    styles: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    cssClass: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    icon: XCircle,
  },
  fed_back: {
    styles: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
    cssClass: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
    icon: CheckCircle,
  },
  timeout: {
    styles: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    cssClass: 'status-timeout',
    icon: Clock,
  },
  planned: {
    styles: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
    cssClass: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
    icon: Clock,
  },
  matched: {
    styles: 'bg-teal-500/20 text-teal-300 border-teal-500/30',
    cssClass: 'bg-teal-500/20 text-teal-300 border-teal-500/30',
    icon: CheckCircle,
  },
  blocked: {
    styles: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    cssClass: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    icon: Clock,
  },
}

/**
 * StatusBadge - Displays experiment/job status with consistent styling
 *
 * @param {string} status - Status value (pending, queued, building, running, completed, failed, cancelled)
 * @param {boolean} showIcon - Whether to show the status icon (default: false)
 * @param {string} size - Badge size: 'sm', 'md' (default: 'md')
 */
export function StatusBadge({ status, showIcon = false, size = 'md', className = '' }) {
  const config = statusConfig[status] || statusConfig.pending
  const Icon = config.icon

  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs',
    md: 'px-2 py-1 text-xs',
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded font-medium border',
        config.styles,
        sizeClasses[size],
        className
      )}
    >
      {showIcon && <Icon className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />}
      {status}
    </span>
  )
}

/**
 * StatusBadgeSimple - Uses CSS class-based styling (for compatibility)
 */
export function StatusBadgeSimple({ status }) {
  const config = statusConfig[status] || statusConfig.pending

  return (
    <span className={clsx('badge', config.cssClass)}>
      {status}
    </span>
  )
}

export default StatusBadge
