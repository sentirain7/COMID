import { useMemo } from 'react'
import { AlertCircle, CheckSquare, Square, XSquare } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'

/**
 * Multi-select experiment panel for curve analysis.
 *
 * Props:
 *   experiments: [{ exp_id, label, binder_type, temperature_k, additive }]
 *   selectedIds: string[]
 *   onSelectionChange: (ids: string[]) => void
 *   loading: boolean
 *   error: any
 *   maxSelection: number (default 8)
 */
export default function ExperimentSelector({
  experiments = [],
  selectedIds = [],
  onSelectionChange,
  loading = false,
  error = null,
  maxSelection = 8,
}) {
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])

  const toggle = (expId) => {
    if (selectedSet.has(expId)) {
      onSelectionChange(selectedIds.filter((id) => id !== expId))
    } else if (selectedIds.length < maxSelection) {
      onSelectionChange([...selectedIds, expId])
    }
  }

  const selectAll = () => {
    onSelectionChange(experiments.slice(0, maxSelection).map((e) => e.exp_id))
  }

  const clearAll = () => {
    onSelectionChange([])
  }

  if (loading) {
    return (
      <div className="p-3 text-xs text-slate-500 text-center">Loading experiments...</div>
    )
  }

  if (error) {
    return (
      <div className="p-3 flex items-center gap-2 text-xs text-red-400">
        <AlertCircle className="w-3 h-3" />
        Failed to load experiments
      </div>
    )
  }

  if (!experiments.length) {
    return (
      <div className="p-3 text-xs text-slate-500 text-center">
        No experiments with this metric found
      </div>
    )
  }

  return (
    <div
      className="rounded-lg border overflow-hidden h-[420px] flex flex-col"
      style={{ backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 border-b flex-shrink-0"
        style={{ borderColor: ANALYSIS_BG.border }}
      >
        <span className="text-xs font-medium" style={{ color: ANALYSIS_BG.text }}>
          Experiments ({selectedIds.length}/{maxSelection})
        </span>
        <div className="flex gap-2">
          <button
            onClick={selectAll}
            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            <CheckSquare className="w-3 h-3" />
            All
          </button>
          <button
            onClick={clearAll}
            className="text-xs text-slate-400 hover:text-slate-300 flex items-center gap-1"
          >
            <XSquare className="w-3 h-3" />
            Clear
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {experiments.map((exp) => {
          const isSelected = selectedSet.has(exp.exp_id)
          const isDisabled = !isSelected && selectedIds.length >= maxSelection

          return (
            <button
              key={exp.exp_id}
              onClick={() => !isDisabled && toggle(exp.exp_id)}
              disabled={isDisabled}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs border-b transition-colors ${
                isDisabled ? 'opacity-40 cursor-not-allowed' : 'hover:brightness-125 cursor-pointer'
              }`}
              style={{ borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.text }}
            >
              {isSelected ? (
                <CheckSquare className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
              ) : (
                <Square className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
              )}
              <span className="truncate flex-1">{exp.label}</span>
              {exp.temperature_k && (
                <span className="text-slate-500 flex-shrink-0">{exp.temperature_k}K</span>
              )}
              {exp.additive && exp.additive !== 'None' && (
                <span className="px-1 py-0.5 rounded bg-purple-500/20 text-purple-300 text-[10px] flex-shrink-0">
                  {exp.additive}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
