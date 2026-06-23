/**
 * Analysis Explorer Tab.
 *
 * Generic analysis interface supporting three dataset modes:
 * - Bulk Binder Cell
 * - Single Molecule
 * - Layered Structure
 */
import { useState, useMemo, useCallback } from 'react'
import { Search, Download } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import { exportChartToCSV } from '../../lib/csvExport'
import { useExplorerCatalog, useExplorerData, useExplorerAggregate } from '../../hooks/useApi'
import ExplorerControls from './ExplorerControls'
import ExplorerChartRenderer from './ExplorerChartRenderer'

const MODE_DEFAULTS = {
  bulk_binder_cell: { x: 'temperature_K', y: 'density', chart: 'scatter', series: 'aging_state' },
  single_molecule: { x: 'temperature_K', y: 'e_intra', chart: 'scatter', series: 'sara_type' },
  layered_structure: { x: 'crystal_material', y: 'adhesion_energy', chart: 'bar', series: 'layer_type' },
}

export default function ExplorerTab() {
  const { data: catalogList } = useExplorerCatalog()

  const [mode, setMode] = useState('bulk_binder_cell')
  const [chartType, setChartType] = useState('scatter')
  const [xAxis, setXAxis] = useState('temperature_K')
  const [yAxis, setYAxis] = useState('density')
  const [seriesAxis, setSeriesAxis] = useState('aging_state')
  const [filters, setFilters] = useState({})

  const catalog = useMemo(
    () => (catalogList || []).find(c => c.mode === mode),
    [catalogList, mode]
  )

  const handleModeChange = useCallback((newMode) => {
    setMode(newMode)
    const defaults = MODE_DEFAULTS[newMode] || MODE_DEFAULTS.bulk_binder_cell
    setXAxis(defaults.x)
    setYAxis(defaults.y)
    setChartType(defaults.chart)
    setSeriesAxis(defaults.series)
    setFilters({})
  }, [])

  const handleFilterToggle = useCallback((key, value) => {
    setFilters(prev => {
      const arr = prev[key] || []
      const next = arr.includes(value) ? arr.filter(v => v !== value) : [...arr, value]
      const updated = { ...prev }
      if (next.length) updated[key] = next; else delete updated[key]
      return updated
    })
  }, [])

  const handleRangeFilter = useCallback((key, min, max) => {
    setFilters(prev => {
      const updated = { ...prev }
      if (min != null || max != null) {
        updated[key] = { min, max }
      } else {
        delete updated[key]
      }
      return updated
    })
  }, [])

  // Build data request
  const dataRequest = useMemo(() => ({
    dataset_mode: mode,
    filters,
    sort: [{ key: xAxis, direction: 'asc' }],
    limit: 500,
    offset: 0,
  }), [mode, filters, xAxis])

  // Build aggregate request for bar charts
  const aggRequest = useMemo(() => {
    if (chartType !== 'bar') return null
    return {
      dataset_mode: mode,
      filters,
      x_dimension: xAxis,
      series_dimension: seriesAxis || null,
      metric: yAxis,
      reducer: 'mean',
    }
  }, [mode, filters, xAxis, yAxis, seriesAxis, chartType])

  const { data: dataResponse, loading: dataLoading } = useExplorerData(dataRequest)
  const { data: aggResponse, loading: aggLoading } = useExplorerAggregate(aggRequest, chartType === 'bar')

  const rows = dataResponse?.rows || []
  const matchedTotal = dataResponse?.matched_total ?? 0
  const returnedTotal = dataResponse?.returned_total ?? 0
  const availableFilters = dataResponse?.available_filters || {}

  const loading = dataLoading || aggLoading

  const handleExportCSV = () => {
    if (!rows.length) return
    const cols = Object.keys(rows[0])
    exportChartToCSV(rows, cols, `explorer_${mode}`)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Search className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-medium text-white">Analysis Explorer</h2>
          {loading && <span className="text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-300">Loading...</span>}
          {matchedTotal > 0 && (
            <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted }}>
              Showing {returnedTotal} of {matchedTotal} matched
            </span>
          )}
        </div>
        <button
          onClick={handleExportCSV}
          disabled={rows.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:brightness-125 disabled:opacity-40"
          style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted, border: `1px solid ${ANALYSIS_BG.border}` }}
        >
          <Download className="w-4 h-4" />CSV
        </button>
      </div>

      {/* Controls */}
      <div className="rounded-lg p-3" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
        <ExplorerControls
          catalog={catalog}
          mode={mode}
          onModeChange={handleModeChange}
          chartType={chartType}
          onChartTypeChange={setChartType}
          xAxis={xAxis}
          onXAxisChange={setXAxis}
          yAxis={yAxis}
          onYAxisChange={setYAxis}
          seriesAxis={seriesAxis}
          onSeriesChange={setSeriesAxis}
          filters={filters}
          onFilterToggle={handleFilterToggle}
          onRangeFilter={handleRangeFilter}
          availableFilters={availableFilters}
        />
      </div>

      {/* Chart Area */}
      <div className="rounded-lg p-4" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
        <ExplorerChartRenderer
          chartType={chartType}
          rows={rows}
          aggregateData={aggResponse}
          xAxis={xAxis}
          yAxis={yAxis}
          seriesAxis={seriesAxis}
          metric={yAxis}
          catalog={catalog}
        />
      </div>

      {/* Always show table below chart */}
      {chartType !== 'table' && rows.length > 0 && (
        <div className="rounded-lg p-3" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: ANALYSIS_BG.textMuted }}>Raw Data ({returnedTotal} rows)</h3>
          <ExplorerChartRenderer chartType="table" rows={rows} catalog={catalog} />
        </div>
      )}
    </div>
  )
}
