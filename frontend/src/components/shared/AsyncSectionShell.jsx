import { Loader2, AlertCircle } from 'lucide-react'
import clsx from 'clsx'

function AsyncSectionShell({ loading, error, empty, children, minHeight = 'min-h-[120px]', className }) {
  return (
    <div className={clsx(minHeight, className)}>
      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 py-4 px-1 text-amber-300 text-xs">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{String(error)}</span>
        </div>
      ) : empty ? (
        <div className="flex items-center justify-center py-6 text-slate-500 text-xs">
          {typeof empty === 'string' ? empty : 'No data available'}
        </div>
      ) : children}
    </div>
  )
}

export default AsyncSectionShell
