// Shared constants and helpers for Single Molecule screens (single + batch)

export const SOURCE_TABS = [
  { key: 'asphalt_binder', label: 'Asphalt Binder' },
  { key: 'single_moles', label: 'Single Moles' },
  { key: 'additives', label: 'Additives' },
]

export const AGING_TABS = [
  { key: 'non_aging', label: 'Non-Aging' },
  { key: 'short_aging', label: 'Short-Term Aging' },
  { key: 'long_aging', label: 'Long-Term Aging' },
]

export const ELIGIBLE_SOURCES = new Set(['asphalt_binder', 'single_moles', 'additives'])

// Fixed protocol config for ProtocolTimeline — colors/names match protocolStageCatalog.json
export const SINGLE_MOL_SELECTED_STAGES = {
  minimize: true,
  nvt_equilibration: true,
}

export const SINGLE_MOL_STAGE_CONFIG = {
  minimize: {
    name: 'Minimize',
    shortName: 'MIN',
    color: '#94A3B8',
    duration_ps: 10,
    orderIndex: 10,
  },
  nvt_equilibration: {
    name: 'NVT Equilibration',
    shortName: 'NVT-eq',
    color: '#F59E0B',
    duration_ps: 300,
    orderIndex: 50,
  },
}

export function inferSourceKey(mol) {
  const sf = String(mol?.structure_file || '').trim()
  if (sf) {
    const [prefix] = sf.split('/')
    if (prefix === 'asphalt_binder') return 'asphalt_binder'
    if (prefix === 'single_moles') return 'single_moles'
    if (prefix === 'additives') return 'additives'
    if (prefix === 'crystal_structures') return 'crystal_structures'
  }
  const molId = String(mol?.mol_id || '')
  if (molId.startsWith('U-') || molId.startsWith('S-') || molId.startsWith('L-')) {
    return 'asphalt_binder'
  }
  return 'single_moles'
}

export function getDisplayTitle(mol) {
  const source = inferSourceKey(mol)
  if (source === 'asphalt_binder' && mol?.base_id) return String(mol.base_id)
  if (source === 'additives') return mol?.short_name || mol?.name || String(mol?.mol_id || '')
  return String(mol?.mol_id || '').replace(/-\d{4}\b/g, '')
}
