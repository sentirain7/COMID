/**
 * Explorer Controls: dataset mode, chart type, axis selectors, filter chips.
 */
import { useState } from 'react'
import { ANALYSIS_BG } from '../../lib/constants'
import { CHART_TYPE_LABELS } from './explorerUtils'

export default function ExplorerControls({
  catalog,
  mode,
  onModeChange,
  chartType,
  onChartTypeChange,
  xAxis,
  onXAxisChange,
  yAxis,
  onYAxisChange,
  seriesAxis,
  onSeriesChange,
  filters,
  onFilterToggle,
  onRangeFilter,
  availableFilters,
}) {
  if (!catalog) return null

  const dims = catalog.dimensions || []
  const metrics = catalog.metrics || []
  const allAxisOptions = [...dims, ...metrics]
  const chartTypes = catalog.chart_types || ['scatter', 'bar', 'table']

  return (
    <div className="space-y-2">
      {/* Row 1: Mode + Chart + Axes */}
      <div className="flex items-center gap-2 flex-wrap">
        <label className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>Dataset:</label>
        <select
          value={mode}
          onChange={(e) => onModeChange(e.target.value)}
          className="text-sm rounded-lg px-2 py-1"
          style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}
        >
          <option value="bulk_binder_cell">Bulk Binder Cell</option>
          <option value="single_molecule">Single Molecule</option>
          <option value="layered_structure">Layered Structure</option>
        </select>

        <span className="mx-1" style={{ color: ANALYSIS_BG.border }}>|</span>

        <label className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>Chart:</label>
        <select
          value={chartType}
          onChange={(e) => onChartTypeChange(e.target.value)}
          className="text-sm rounded-lg px-2 py-1"
          style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}
        >
          {chartTypes.map(ct => (
            <option key={ct} value={ct}>{CHART_TYPE_LABELS[ct] || ct}</option>
          ))}
        </select>

        <span className="mx-1" style={{ color: ANALYSIS_BG.border }}>|</span>

        <label className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>X:</label>
        <select
          value={xAxis}
          onChange={(e) => onXAxisChange(e.target.value)}
          className="text-sm rounded-lg px-2 py-1"
          style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}
        >
          {allAxisOptions.map(opt => (
            <option key={opt.key} value={opt.key}>{opt.label}</option>
          ))}
        </select>

        <label className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>Y:</label>
        <select
          value={yAxis}
          onChange={(e) => onYAxisChange(e.target.value)}
          className="text-sm rounded-lg px-2 py-1"
          style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}
        >
          {allAxisOptions.map(opt => (
            <option key={opt.key} value={opt.key}>{opt.label}</option>
          ))}
        </select>

        <label className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>Series:</label>
        <select
          value={seriesAxis || ''}
          onChange={(e) => onSeriesChange(e.target.value || null)}
          className="text-sm rounded-lg px-2 py-1"
          style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}
        >
          <option value="">None</option>
          {dims.filter(d => d.type === 'categorical').map(opt => (
            <option key={opt.key} value={opt.key}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Row 2: Categorical filter chips */}
      {availableFilters && Object.keys(availableFilters).length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>Filters:</span>
          {Object.entries(availableFilters).map(([key, info]) => {
            if (!info?.values?.length) return null
            const selected = filters[key] || []
            return info.values.slice(0, 10).map(val => (
              <button
                key={`${key}-${val}`}
                onClick={() => onFilterToggle(key, val)}
                className={`px-2 py-0.5 rounded text-xs border transition-colors ${selected.includes(val) ? 'bg-violet-500/20 border-violet-400/50 text-violet-300' : ''}`}
                style={!selected.includes(val) ? { backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.textMuted } : {}}
              >
                {val}
              </button>
            ))
          })}
        </div>
      )}

      {/* Row 3: Range filters */}
      {availableFilters && (
        <RangeFilters availableFilters={availableFilters} filters={filters} onRangeFilter={onRangeFilter} />
      )}
    </div>
  )
}

function RangeFilters({ availableFilters, filters, onRangeFilter }) {
  const rangeKeys = Object.entries(availableFilters)
    .filter(([, info]) => info?.min !== undefined && info?.values === undefined)
    .map(([key]) => key)

  const [drafts, setDrafts] = useState({})

  if (!rangeKeys.length || !onRangeFilter) return null

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {rangeKeys.map(key => {
        const info = availableFilters[key]
        const applied = filters[key] || {}
        const draft = drafts[key] || applied
        return (
          <div key={key} className="flex items-center gap-1">
            <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>{key}:</span>
            <input type="number" placeholder={info.min != null ? String(info.min) : 'Min'}
              value={draft.min ?? ''} onChange={e => setDrafts(prev => ({ ...prev, [key]: { ...prev[key], min: e.target.value } }))}
              className="w-16 text-xs rounded px-1 py-0.5" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }} />
            <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>-</span>
            <input type="number" placeholder={info.max != null ? String(info.max) : 'Max'}
              value={draft.max ?? ''} onChange={e => setDrafts(prev => ({ ...prev, [key]: { ...prev[key], max: e.target.value } }))}
              className="w-16 text-xs rounded px-1 py-0.5" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }} />
            <button onClick={() => {
              const d = drafts[key] || {}
              onRangeFilter(key, d.min ? Number(d.min) : null, d.max ? Number(d.max) : null)
            }} className="px-1.5 py-0.5 rounded text-xs bg-blue-500/20 border border-blue-400/50 text-blue-300">OK</button>
            <button onClick={() => {
              setDrafts(prev => ({ ...prev, [key]: {} }))
              onRangeFilter(key, null, null)
            }} className="px-1.5 py-0.5 rounded text-xs" style={{ color: ANALYSIS_BG.textMuted }}>x</button>
          </div>
        )
      })}
    </div>
  )
}
