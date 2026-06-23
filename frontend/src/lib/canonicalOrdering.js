/**
 * Canonical ordering utilities for analysis charts.
 *
 * Must agree with backend: src/features/common/canonical_ordering.py
 */

export const AGING_SORT = { non_aging: 0, short_aging: 1, long_aging: 2 }

export const LAYER_TYPE_SORT = {
  interface: 0,
  'water-interface': 1,
  '3-layer': 2,
  'aged-fresh': 3,
  'water-aged-fresh': 4,
  'binder-binder': 5,
}

export const BINDER_SORT = { A1: 0, K1: 1, M1: 2, C: 3 }

const NONE_VALUES = new Set(['none', 'None', '', null, undefined])

/**
 * Return a comparable key tuple [priority, label] for a dimension value.
 */
export function canonicalValueKey(dimension, value) {
  const label = value != null ? String(value) : ''
  const dim = (dimension || '').toLowerCase().replace(/-/g, '_')

  if (dim === 'aging' || dim === 'aging_state') {
    return [AGING_SORT[label] ?? 99, label]
  }
  if (dim === 'layer_type') {
    return [LAYER_TYPE_SORT[label] ?? 99, label]
  }
  if (dim === 'binder' || dim === 'binder_type') {
    return [BINDER_SORT[label] ?? 99, label]
  }
  if (dim === 'additive' || dim === 'additive_type') {
    return [NONE_VALUES.has(value) ? 0 : 1, label.toLowerCase()]
  }
  if (dim === 'temperature_k' || dim === 'temperature') {
    const n = parseFloat(value)
    return [isNaN(n) ? 99 : 0, isNaN(n) ? label : n.toFixed(4).padStart(12, '0')]
  }
  return [99, label]
}

/**
 * Compare two values within a dimension using canonical ordering.
 */
export function canonicalCompare(dimension, a, b) {
  const ka = canonicalValueKey(dimension, a)
  const kb = canonicalValueKey(dimension, b)
  if (ka[0] !== kb[0]) return ka[0] - kb[0]
  return ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0
}

/**
 * Sort an array of values using canonical ordering for a dimension.
 */
export function canonicalSort(dimension, values) {
  return [...values].sort((a, b) => canonicalCompare(dimension, a, b))
}
