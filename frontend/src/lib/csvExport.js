/**
 * CSV Export Utility
 *
 * Exports chart data to CSV format for use in external tools (Origin, Excel, etc.)
 */

/**
 * Convert data array to CSV string
 * @param {Object[]} data - Array of data objects
 * @param {string[]} columns - Column keys to include
 * @param {Object} headers - Optional column headers mapping { key: 'Display Header' }
 * @returns {string} CSV formatted string
 */
export function toCSV(data, columns, headers = {}) {
  if (!data || !data.length) return ''

  // Build header row
  const headerRow = columns.map((col) => headers[col] || col).join(',')

  // Build data rows
  const dataRows = data.map((row) =>
    columns
      .map((col) => {
        const val = row[col]
        if (val === null || val === undefined) return ''
        if (typeof val === 'string' && val.includes(',')) return `"${val}"`
        return val
      })
      .join(',')
  )

  return [headerRow, ...dataRows].join('\n')
}

/**
 * Download data as CSV file
 * @param {string} csvContent - CSV string content
 * @param {string} filename - Filename without extension
 */
export function downloadCSV(csvContent, filename) {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)
  link.setAttribute('href', url)
  link.setAttribute('download', `${filename}.csv`)
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/**
 * Export chart data to CSV and trigger download
 * @param {Object[]} data - Chart data array
 * @param {string[]} columns - Column keys
 * @param {string} filename - Base filename
 * @param {Object} headers - Optional headers mapping
 */
export function exportChartToCSV(data, columns, filename, headers = {}) {
  const csv = toCSV(data, columns, headers)
  downloadCSV(csv, filename)
}

/**
 * Export multi-series chart data to CSV
 * Each series gets its own columns with labeled headers
 * @param {Object[]} data - Merged chart data
 * @param {string} xKey - X-axis key
 * @param {Object[]} series - Series info [{ key, label }]
 * @param {string} filename - Base filename
 * @param {Object} axisLabels - Axis labels { x: 'X Label', y: 'Y Label' }
 */
export function exportMultiSeriesToCSV(data, xKey, series, filename, axisLabels = {}) {
  if (!data || !data.length) return

  const columns = [xKey, ...series.map((s) => s.key)]
  const headers = {
    [xKey]: axisLabels.x || xKey,
    ...Object.fromEntries(series.map((s) => [s.key, s.label || s.key])),
  }

  exportChartToCSV(data, columns, filename, headers)
}

/**
 * Export property vs temperature data
 * @param {Object[]} data - Data with temperature_k and property values
 * @param {string} propertyName - Property metric name
 * @param {string} propertyLabel - Property display label with unit
 * @param {string} filename - Base filename
 */
export function exportPropertyTemperature(data, propertyName, propertyLabel, filename) {
  const columns = ['temperature_k', propertyName]
  const headers = {
    temperature_k: 'Temperature (K)',
    [propertyName]: propertyLabel,
  }
  exportChartToCSV(data, columns, filename, headers)
}

/**
 * Export grouped bar chart data
 * @param {Object[]} data - Data with category and values
 * @param {string} categoryKey - Category key
 * @param {string[]} valueKeys - Value column keys
 * @param {Object} headers - Headers mapping
 * @param {string} filename - Base filename
 */
export function exportGroupedBarData(data, categoryKey, valueKeys, headers, filename) {
  const columns = [categoryKey, ...valueKeys]
  exportChartToCSV(data, columns, filename, headers)
}
