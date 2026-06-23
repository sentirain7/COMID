/**
 * Shared utilities for layered-structure 3D scatter charts.
 *
 * Used by LayeredAnalysisTab and GHGAnalysisTab to avoid duplication.
 */

import { LAYERED_3D_AXIS_OPTIONS, AGING_ANALYSIS_COLORS } from '../../lib/constants'
import { canonicalSort } from '../../lib/canonicalOrdering'
import { getAnalysisCrystalColor, getAnalysisLayerTypeColor, ANALYSIS_BINDER } from '../../lib/colorPresets'

export function getLayeredPointColor(item, colorBy) {
  switch (colorBy) {
    case 'crystal_material': return getAnalysisCrystalColor(item.crystal_material)
    case 'layer_type': return getAnalysisLayerTypeColor(item.layer_type)
    case 'aging_state': return AGING_ANALYSIS_COLORS[item.aging_state] || '#888'
    case 'binder_type': return ANALYSIS_BINDER[item.binder_type] || ANALYSIS_BINDER.unknown || '#888'
    case 'has_water': return item.has_water ? '#06b6d4' : '#60a5fa'
    default: return getAnalysisLayerTypeColor(item.layer_type)
  }
}

export function normalize(values, span = 12) {
  if (!values.length) return []
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  return values.map((v) => ((v - min) / range - 0.5) * span)
}

/**
 * Deterministic jitter based on a string hash.
 * Same (expId, axisKey, categoryValue) always produces the same offset.
 */
function deterministicJitter(expId, axisKey, categoryValue) {
  const str = `${expId}|${axisKey}|${categoryValue}`
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0
  }
  return ((hash & 0x7fffffff) / 0x7fffffff - 0.5) * 0.2
}

export function encodeCategorical(values, span = 12, items = null, axisKey = '') {
  const unique = canonicalSort(axisKey, [...new Set(values.filter(Boolean))])
  const map = Object.fromEntries(unique.map((v, i) => [v, i]))
  const encoded = values.map((v, i) => {
    const idx = map[v] ?? 0
    const expId = items && items[i] ? (items[i].exp_id || '') : String(i)
    const jitter = deterministicJitter(expId, axisKey, v)
    return unique.length > 1 ? ((idx / (unique.length - 1)) - 0.5) * span + jitter : jitter
  })
  return { encoded, categories: unique }
}

export function buildScatterData(items, axisX, axisY, axisZ) {
  if (!items?.length) return { points: [], catX: null, catY: null, catZ: null }
  const optX = LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === axisX)
  const optY = LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === axisY)
  const optZ = LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === axisZ)

  const filtered = items.filter((it) => {
    if (optX?.type === 'continuous' && it[axisX] == null) return false
    if (optY?.type === 'continuous' && it[axisY] == null) return false
    if (optZ?.type === 'continuous' && it[axisZ] == null) return false
    return true
  })
  if (!filtered.length) return { points: [], catX: null, catY: null, catZ: null }

  const rawX = filtered.map((it) => optX?.type === 'categorical' ? String(it[axisX] ?? '') : Number(it[axisX]))
  const rawY = filtered.map((it) => optY?.type === 'categorical' ? String(it[axisY] ?? '') : Number(it[axisY]))
  const rawZ = filtered.map((it) => optZ?.type === 'categorical' ? String(it[axisZ] ?? '') : Number(it[axisZ]))

  let xPos, yPos, zPos, catX = null, catY = null, catZ = null
  if (optX?.type === 'categorical') { const r = encodeCategorical(rawX, 12, filtered, axisX); xPos = r.encoded; catX = r.categories } else xPos = normalize(rawX)
  if (optY?.type === 'categorical') { const r = encodeCategorical(rawY, 10, filtered, axisY); yPos = r.encoded; catY = r.categories } else yPos = normalize(rawY, 10)
  if (optZ?.type === 'categorical') { const r = encodeCategorical(rawZ, 12, filtered, axisZ); zPos = r.encoded; catZ = r.categories } else zPos = normalize(rawZ)

  const points = filtered.map((it, i) => ({
    ...it,
    position: [xPos[i], yPos[i], zPos[i]],
  }))
  return { points, catX, catY, catZ }
}
