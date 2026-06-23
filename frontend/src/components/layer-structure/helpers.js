import { sanitizeNameToken } from '../../lib/formatters'
import { LAYER_BOUNDARY_MODE } from './config'

let ROW_SEQ = 1
export const nextRowId = () => `layer-row-${ROW_SEQ++}`

export const createLayerRow = (sourceType = 'binder_cell') => ({
  rowId: nextRowId(),
  sourceType,
  sourceId: '',
  autoMatchMaterial: '',
  autoSelected: false,   // true when crystal was auto-picked to match an adjacent layer
  label: '',
  gapAfter: '',
})

/** Find the best-matching crystal source for a given target XY size within the same material. */
export function findBestCrystalMatch(targetLx, targetLy, material, crystalSources) {
  if (crystalSources.length === 0 || !Number.isFinite(targetLx) || !Number.isFinite(targetLy))
    return null
  let best = null
  let bestErr = Infinity
  crystalSources.forEach((src) => {
    if (!src.box_size || src.box_size.length < 2) return
    if (material && src.material && src.material !== material) return
    const err = Math.max(Math.abs(src.box_size[0] - targetLx), Math.abs(src.box_size[1] - targetLy))
    if (err < bestErr) {
      bestErr = err
      best = src
    }
  })
  return best
}

/** Get the material of a currently-selected crystal source. */
export function getCrystalMaterial(sourceId, crystalSources) {
  if (!sourceId) return null
  return crystalSources.find((s) => s.source_id === sourceId)?.material || null
}

/**
 * For each crystal layer, auto-pick the crystal source whose XY best matches
 * the nearest non-crystal layer above it.
 */
export function autoMatchCrystalLayers(layerList, sourceCatalog) {
  const crystals = sourceCatalog.crystal_structure || []
  return layerList.map((row, idx) => {
    if (row.sourceType !== 'crystal_structure') return row
    if (row.autoMatchMaterial) return row
    const material = getCrystalMaterial(row.sourceId, crystals)
    let refBox = null
    for (let i = idx + 1; i < layerList.length; i++) {
      const above = layerList[i]
      if (above.sourceType === 'crystal_structure') continue
      const aboveSources = sourceCatalog[above.sourceType] || []
      const aboveSrc = above.sourceId
        ? aboveSources.find((s) => s.source_id === above.sourceId)
        : null
      if (aboveSrc?.box_size?.length >= 2) {
        refBox = aboveSrc.box_size
      }
      break
    }
    if (!refBox) return row
    const bestCrystal = findBestCrystalMatch(refBox[0], refBox[1], material, crystals)
    if (!bestCrystal) return row
    if (bestCrystal.source_id === row.sourceId) return row
    return { ...row, sourceId: bestCrystal.source_id, autoSelected: true }
  })
}

/** Compute per-layer XY mismatch errors for crystal layers vs. nearest non-crystal above. */
export function computeLayerXYErrors(layers, sourceCatalog) {
  const errors = new Map() // rowId -> { errorPct, refXY, thisXY }
  layers.forEach((row, idx) => {
    if (row.sourceType !== 'crystal_structure') return
    const sources = sourceCatalog[row.sourceType] || []
    const thisSource = row.sourceId ? sources.find((s) => s.source_id === row.sourceId) : null
    const thisBox = thisSource?.box_size
    if (!thisBox || thisBox.length < 2) return

    // Find nearest non-crystal layer above (higher index = higher z)
    let refBox = null
    for (let i = idx + 1; i < layers.length; i++) {
      const above = layers[i]
      if (above.sourceType === 'crystal_structure') continue
      const aboveSources = sourceCatalog[above.sourceType] || []
      const aboveSrc = above.sourceId ? aboveSources.find((s) => s.source_id === above.sourceId) : null
      if (aboveSrc?.box_size?.length >= 2) {
        refBox = aboveSrc.box_size
      }
      break // stop at nearest non-crystal regardless
    }
    if (!refBox) return

    const dx = Math.abs(thisBox[0] - refBox[0])
    const dy = Math.abs(thisBox[1] - refBox[1])
    const refAvg = (refBox[0] + refBox[1]) / 2
    if (refAvg <= 0) return
    const errorPct = (Math.max(dx, dy) / refAvg) * 100
    errors.set(row.rowId, {
      errorPct,
      refXY: [refBox[0], refBox[1]],
      thisXY: [thisBox[0], thisBox[1]],
    })
  })
  return errors
}

/** Generate an auto-name for the layered structure experiment. */
export function generateAutoName(layers, temperatureK, ffType, pressureAtm) {
  const layerToken = layers
    .map((row, index) => {
      const sourceToken = row.sourceId || `${row.sourceType}${index + 1}`
      return sanitizeNameToken(sourceToken)
    })
    .join('-')
  const tempToken = `${Math.round(Number(temperatureK) || 0)}K`
  const ffToken = sanitizeNameToken(ffType)
  const pressureToken = `${Number(pressureAtm || 0).toFixed(2).replace('.', 'p')}atm`
  const boundaryToken = LAYER_BOUNDARY_MODE.toUpperCase()
  return `layered_${layerToken}_${ffToken}_${tempToken}_${pressureToken}_${boundaryToken}`
}

export function statusTone(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'pass') return 'text-emerald-300 bg-emerald-500/20'
  if (s === 'warn') return 'text-amber-300 bg-amber-500/20'
  return 'text-red-300 bg-red-500/20'
}

export function formatCheckDetails(code, details) {
  if (!details || typeof details !== 'object') return null
  const n = (v) => Number(v).toFixed(2)
  switch (code) {
    case 'xy_alignment': {
      const base = details.base_xy
      if (!base) return null
      const parts = [`Base XY: ${n(base[0])} x ${n(base[1])} Å`]
      // New response: % display
      if (details.max_mismatch_pct != null) parts.push(`ΔXY=${n(details.max_mismatch_pct)}%`)
      if (details.tolerance_pct != null) parts.push(`tol=${n(details.tolerance_pct)}%`)
      // Backward compat: old response (Å)
      else {
        if (details.max_dx != null) parts.push(`ΔX=${n(details.max_dx)}`)
        if (details.max_dy != null) parts.push(`ΔY=${n(details.max_dy)}`)
        if (details.tolerance != null) parts.push(`tol=${n(details.tolerance)}`)
      }
      return parts.join('  |  ')
    }
    case 'aspect_ratio': {
      const parts = []
      if (details.xy_to_z_ratio != null) parts.push(`XY/Z = ${n(details.xy_to_z_ratio)}`)
      if (details.required_min_ratio != null) parts.push(`min = ${n(details.required_min_ratio)}`)
      return parts.join('  |  ') || null
    }
    case 'z_thickness': {
      if (!details.z_sizes?.length) return null
      return `Z: ${details.z_sizes.map((z) => n(z) + ' Å').join(', ')}`
    }
    default:
      return null
  }
}

export function renderSourceLabel(item) {
  const parts = [item.name]
  if (item.box_size?.length === 3) {
    const [lx, ly, lz] = item.box_size
    parts.push(`${Number(lx).toFixed(1)}x${Number(ly).toFixed(1)}x${Number(lz).toFixed(1)} A`)
  }
  if (item.atom_count) {
    parts.push(`${Number(item.atom_count).toLocaleString()} atoms`)
  }
  return parts.join(' | ')
}
