export function getAdditiveDisplayName(molId, additiveCatalog = {}) {
  const item = additiveCatalog?.[molId] || null
  // Prefer short_name over name for compact display
  return item?.short_name || item?.name || molId || ''
}

export function getAdditiveDisplayLabel(molId, additiveCatalog = {}) {
  const item = additiveCatalog?.[molId] || null
  const shortName = item?.short_name || item?.name || molId
  if (!molId) return shortName
  // Use short_name as primary label, add mol_id only if different
  return shortName === molId ? molId : shortName
}
