/**
 * Pure utility functions for TransitionsTab.
 *
 * No React hooks — data transformations, formatting, constants only.
 */

export const GHG_GROUP_OPTIONS = [
  { value: 'binder', label: 'Binder' },
  { value: 'aging', label: 'Aging' },
  { value: 'additive', label: 'Additive' },
]

export function formatGHG(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(3) : '-'
}

/**
 * Group GHG data points by the selected category and calculate statistics.
 *
 * @param {Array} ghgData - Raw GHG data points from API.
 * @param {string} ghgGroupBy - Grouping category ('binder' | 'aging' | 'additive').
 * @returns {{ groups: Array, globalStats: object|null }}
 */
export function computeGhgGroupedData(ghgData, ghgGroupBy) {
  if (!Array.isArray(ghgData) || ghgData.length === 0) return { groups: [], globalStats: null }

  const groups = new Map()

  ghgData.forEach(point => {
    let groupKey
    if (ghgGroupBy === 'binder') {
      groupKey = point.binder_type || 'unknown'
    } else if (ghgGroupBy === 'aging') {
      groupKey = point.aging_state || 'non_aging'
    } else {
      groupKey = point.additive || 'none'
    }

    if (!groups.has(groupKey)) {
      groups.set(groupKey, { key: groupKey, values: [], count: 0 })
    }
    const g = groups.get(groupKey)
    const ghgVal = Number(point.axis_z_value)
    if (Number.isFinite(ghgVal)) {
      g.values.push(ghgVal)
      g.count++
    }
  })

  // Calculate mean, min, max for each group
  const result = []
  let allValues = []

  groups.forEach((g, key) => {
    if (g.values.length === 0) return
    const mean = g.values.reduce((s, v) => s + v, 0) / g.values.length
    const min = Math.min(...g.values)
    const max = Math.max(...g.values)
    const variance = g.values.reduce((s, v) => s + Math.pow(v - mean, 2), 0) / g.values.length
    const std = Math.sqrt(variance)

    allValues = allValues.concat(g.values)

    // Format label based on group type
    let label = key
    if (ghgGroupBy === 'aging') {
      const agingLabels = { non_aging: 'NA (Virgin)', short_aging: 'SA (RTFOT)', long_aging: 'LA (PAV)' }
      label = agingLabels[key] || key
    } else if (ghgGroupBy === 'additive' && key === 'none') {
      label = 'No Additive'
    }

    result.push({ key, label, mean, min, max, std, count: g.count })
  })

  // Sort by mean GHG (ascending = better)
  result.sort((a, b) => a.mean - b.mean)

  // Global statistics
  const globalMean = allValues.length > 0
    ? allValues.reduce((s, v) => s + v, 0) / allValues.length
    : 0
  const globalMin = allValues.length > 0 ? Math.min(...allValues) : 0
  const globalMax = allValues.length > 0 ? Math.max(...allValues) : 1

  return {
    groups: result,
    globalStats: {
      mean: globalMean,
      min: globalMin,
      max: globalMax,
      total: allValues.length,
    },
  }
}

/**
 * Compute bar chart configuration from grouped GHG data.
 *
 * @param {{ groups: Array, globalStats: object|null }} ghgGroupedData
 * @returns {{ bars: Array, baseline: number, range: number }}
 */
export function computeChartConfig(ghgGroupedData) {
  const { groups, globalStats } = ghgGroupedData
  if (!groups.length || !globalStats) return { bars: [], baseline: 0, range: 1 }

  const values = groups.map(g => g.mean)
  const minVal = Math.min(...values)
  const maxVal = Math.max(...values)

  // Use dynamic baseline: start from 90% of min value to emphasize differences
  const baseline = minVal * 0.9
  const range = maxVal - baseline

  const bars = groups.map(g => {
    const heightPct = range > 0 ? ((g.mean - baseline) / range) * 100 : 50
    const deviationFromMean = globalStats.mean > 0
      ? ((g.mean - globalStats.mean) / globalStats.mean) * 100
      : 0

    return {
      ...g,
      heightPct: Math.max(5, Math.min(100, heightPct)),
      deviation: deviationFromMean,
      isAboveMean: g.mean > globalStats.mean,
    }
  })

  return { bars, baseline, range }
}
