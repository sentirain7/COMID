export const COHESIVE_ENERGY_DENSITY_PROFILE_METRIC = 'cohesive_energy_density_profile'

export function getCohesiveEnergyDensityProfileRows(columns = {}) {
  const layerIndices = Array.isArray(columns?.layer_index) ? columns.layer_index : []
  const layerLabels = Array.isArray(columns?.layer_label) ? columns.layer_label : []
  const cedValues = Array.isArray(columns?.ced_MJ_m3) ? columns.ced_MJ_m3 : []
  const volumes = Array.isArray(columns?.volume_A3) ? columns.volume_A3 : []
  const rowCount = Math.max(
    layerIndices.length,
    layerLabels.length,
    cedValues.length,
    volumes.length,
  )

  return Array.from({ length: rowCount }, (_, index) => ({
    rowId: `${layerIndices[index] ?? index + 1}-${layerLabels[index] ?? index}`,
    layer_index: layerIndices[index] ?? index + 1,
    layer_label: layerLabels[index] ?? `Layer ${index + 1}`,
    ced_MJ_m3: cedValues[index] ?? null,
    volume_A3: volumes[index] ?? null,
  })).filter((row) => row.ced_MJ_m3 != null || row.volume_A3 != null)
}

export function mergeCohesiveEnergyDensityProfileExperiments(experiments = []) {
  const rowsByLayer = new Map()
  const series = []

  experiments.forEach((experiment, index) => {
    const rows = getCohesiveEnergyDensityProfileRows(experiment?.columns)
    if (!rows.length) return

    const key = `ced_${index}`
    series.push({
      key,
      label: experiment?.label || experiment?.expId || `Experiment ${index + 1}`,
      index,
    })

    rows.forEach((row) => {
      const layerIndex = Number(row.layer_index)
      const safeLayerIndex = Number.isFinite(layerIndex) ? layerIndex : index + 1
      const existing = rowsByLayer.get(safeLayerIndex) || {
        layer_index: safeLayerIndex,
        layer_label: row.layer_label,
      }

      rowsByLayer.set(safeLayerIndex, {
        ...existing,
        layer_label: existing.layer_label || row.layer_label,
        [key]: row.ced_MJ_m3,
      })
    })
  })

  const data = [...rowsByLayer.values()].sort((left, right) => left.layer_index - right.layer_index)
  return { data, series }
}
