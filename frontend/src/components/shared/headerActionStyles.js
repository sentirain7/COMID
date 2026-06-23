export const HEADER_ACTION_BUTTON_BASE =
  'flex items-center gap-1.5 px-3 py-1.5 rounded text-xs border transition-colors'

export const HEADER_ACTION_BUTTON =
  `${HEADER_ACTION_BUTTON_BASE} text-slate-200 bg-slate-700/60 border-slate-600 hover:bg-slate-700`

// Legacy aliases kept to avoid churn at call sites; all top-level header
// actions intentionally share the same visual design.
export const HEADER_ACTION_PRIMARY = HEADER_ACTION_BUTTON
export const HEADER_ACTION_SECONDARY = HEADER_ACTION_BUTTON
