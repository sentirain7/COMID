import clsx from 'clsx'
import { SECTION_TITLE_CLASS } from './config'
import { statusTone, formatCheckDetails } from './helpers'

function LayerChecksPanel({ previewData }) {
  return (
    <div className="text-sm text-slate-300 flex flex-col">
      <div className={SECTION_TITLE_CLASS}>Layer Checks</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1">
        {previewData?.checks?.length > 0 ? (
          <div className="space-y-1.5">
            {previewData.checks.map((check, idx) => {
              const detail = formatCheckDetails(check.code, check.details)
              return (
                <div key={`${check.code}_${idx}`}>
                  <div className="flex items-start gap-2 text-xs">
                    <span className={clsx('px-1.5 py-0.5 rounded uppercase tracking-wide text-[10px] shrink-0', statusTone(check.status))}>
                      {check.status}
                    </span>
                    <span className="text-slate-200">{check.message}</span>
                  </div>
                  {detail && (
                    <div className="ml-[42px] text-[10px] font-mono text-slate-400 mt-0.5">
                      {detail}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="text-[11px] text-slate-500 flex items-center justify-center h-full min-h-[60px]">
            Press &ldquo;Preview Stack&rdquo; to run layer checks.
          </div>
        )}
      </div>
    </div>
  )
}

export default LayerChecksPanel
