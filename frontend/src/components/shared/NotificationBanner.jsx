import { X } from 'lucide-react'
import clsx from 'clsx'

const STYLE_MAP = {
  error: 'bg-slate-900 border-t-2 border-red-500/50 text-red-300',
  warning: 'bg-slate-900 border-t-2 border-amber-500/50 text-amber-300',
  info: 'bg-slate-900 border-t-2 border-blue-500/50 text-blue-300',
  success: 'bg-slate-900 border-t-2 border-emerald-500/50 text-emerald-300',
}

function NotificationBanner({ notification, onDismiss }) {
  if (!notification) return null

  return (
    <div
      className={clsx(
        'fixed bottom-0 left-72 right-0 z-50 px-4 py-2.5 text-sm flex items-center justify-between shadow-lg',
        STYLE_MAP[notification.type] || STYLE_MAP.info
      )}
    >
      <span>{notification.message}</span>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="ml-2 opacity-60 hover:opacity-100">
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}

export default NotificationBanner
