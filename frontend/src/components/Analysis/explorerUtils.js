/**
 * Analysis Explorer utility functions.
 */

/**
 * Infer the best chart type from axis dimension types.
 */
export function inferChartType(catalog, xDim, yDim) {
  if (!catalog) return 'table'
  const dims = catalog.dimensions || []
  const xDef = dims.find(d => d.key === xDim)
  const yDef = dims.find(d => d.key === yDim)

  const xType = xDef?.type || 'categorical'
  const yType = yDef?.type || 'categorical'

  if (xType === 'continuous' && yType === 'continuous') return 'scatter'
  if (xType === 'categorical') return 'bar'
  return 'scatter'
}

/**
 * Format metric value for display.
 */
export function formatMetricValue(val, precision = 4) {
  if (val == null) return '-'
  if (typeof val !== 'number') return String(val)
  if (Math.abs(val) < 0.001 && val !== 0) return val.toExponential(2)
  return val.toPrecision(precision)
}

/**
 * Map chart type to human label.
 */
export const CHART_TYPE_LABELS = {
  scatter: 'Scatter',
  line: 'Line',
  bar: 'Bar',
  scatter3d: '3D Scatter',
  table: 'Table',
}
