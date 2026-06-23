/**
 * Pure utility functions for the Molecules view.
 *
 * No React imports — these are plain helpers consumed by Molecules.jsx
 * and its sub-components.
 */

export const PAGE_TAB_CONFIG = [
  { key: 'library', label: 'Library' },
  { key: 'dynamics', label: 'Dynamics' },
]

export const TAB_CONFIG = [
  { key: 'asphalt_binder', label: 'Asphalt Binder' },
  { key: 'single_moles', label: 'Single Moles' },
  { key: 'additives', label: 'Additives' },
  { key: 'crystal_structures', label: 'Crystal Structures' },
]

export const AGING_TAB_CONFIG = [
  { key: 'non_aging', label: 'Non-Aging' },
  { key: 'short_aging', label: 'Short-Term Aging' },
  { key: 'long_aging', label: 'Long-Term Aging' },
]

/**
 * Infer which source tab a molecule belongs to based on its
 * structure_file path prefix or mol_id prefix.
 *
 * Args:
 *   mol: molecule object with optional structure_file and mol_id fields
 *
 * Returns:
 *   One of 'asphalt_binder' | 'single_moles' | 'additives' | 'crystal_structures'
 */
export function inferSourceKey(mol) {
  const structureFile = String(mol?.structure_file || '').trim()
  if (structureFile) {
    const [prefix] = structureFile.split('/')
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

/**
 * Build a human-friendly display title for a molecule.
 *
 * Args:
 *   mol: molecule object
 *
 * Returns:
 *   Display title string
 */
export function getDisplayMolTitle(mol) {
  const source = inferSourceKey(mol)
  if (source === 'asphalt_binder' && mol?.base_id) {
    return String(mol.base_id)
  }
  if (source === 'additives') {
    return mol?.short_name || mol?.name || String(mol?.mol_id || '')
  }
  return String(mol?.mol_id || '').replace(/-\d{4}\b/g, '')
}
