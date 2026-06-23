import { ADDITIVE_COLORS, generateAdditiveColor, getGlowConfig } from './colorPresets'

/**
 * Resolve the display color for an additive type.
 *
 * Lookup order:
 *   1. Preset ADDITIVE_COLORS (known additives)
 *   2. generateAdditiveColor() (unknown/new additives — deterministic hash)
 *
 * @param {string|null|undefined} additive - Additive type name
 * @returns {string} Hex color
 */
export const getAdditiveColor = (additive) => {
  if (!additive || additive === 'None') return ADDITIVE_COLORS.base
  return ADDITIVE_COLORS[additive] || generateAdditiveColor(additive)
}

export const getPointStyle = (point) => {
  const isThisWeek = point.data_age === 'today' || point.data_age === 'current_session'
  return {
    opacity: isThisWeek ? 1 : 0.5,
    border: isThisWeek ? '2px solid white' : 'none',
  }
}

/**
 * Build a box-shadow glow style for a data point.
 *
 * Returns an empty object when the active preset has glow disabled.
 *
 * @param {string} color - Hex color of the data point
 * @returns {object} Style object with boxShadow (or empty)
 */
export const getGlowStyle = (color) => {
  const glow = getGlowConfig()
  if (!glow || !color || !color.startsWith('#')) return {}
  const opacityHex = Math.round(glow.opacity * 255)
    .toString(16)
    .padStart(2, '0')
  return {
    boxShadow: `0 0 ${glow.blur}px ${glow.spread}px ${color}${opacityHex}`,
  }
}

export const getDataAgeClass = (dataAge) => {
  if (dataAge === 'current_session') return 'text-blue-300'
  if (dataAge === 'today') return 'text-green-300'
  return 'text-slate-500'
}

export const getDataAgeLabel = (dataAge) => {
  if (dataAge === 'current_session') return 'Current Session'
  if (dataAge === 'today') return 'Today'
  return 'Historical'
}

// Color palette for charts (index-based)
const CHART_COLORS = [
  '#3b82f6', // blue
  '#ef4444', // red
  '#10b981', // emerald
  '#f59e0b', // amber
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#f97316', // orange
  '#84cc16', // lime
  '#a855f7', // purple
]

/**
 * Get a color from a fixed palette by index.
 * Useful for chart series where order is deterministic.
 *
 * @param {number} index - Dataset index
 * @returns {string} Hex color
 */
export const getChartColorByIndex = (index) => {
  return CHART_COLORS[index % CHART_COLORS.length]
}
