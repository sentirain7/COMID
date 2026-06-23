/**
 * Interface Molecules configuration
 *
 * Environment molecules for layered structure interface layers.
 * Note: Primary source is API response from single_moles.yaml SSOT.
 * This config provides fallback defaults and UI helpers.
 */

export const INTERFACE_MOLECULE_INFO = {
  // Deicing agents
  NaCl: {
    category: 'deicing',
    name: 'Sodium Chloride',
    formula: 'NaCl',
    atoms: 2,
    mw: 58.44,
    elements: ['Na', 'Cl'],
    defaultDensity: 2.16,
  },
  CaCl2: {
    category: 'deicing',
    name: 'Calcium Chloride',
    formula: 'CaCl\u2082',
    atoms: 3,
    mw: 110.98,
    elements: ['Ca', 'Cl'],
    defaultDensity: 2.15,
  },
  MgCl2: {
    category: 'deicing',
    name: 'Magnesium Chloride',
    formula: 'MgCl\u2082',
    atoms: 3,
    mw: 95.21,
    elements: ['Mg', 'Cl'],
    defaultDensity: 2.32,
  },
  KCl: {
    category: 'deicing',
    name: 'Potassium Chloride',
    formula: 'KCl',
    atoms: 2,
    mw: 74.55,
    elements: ['K', 'Cl'],
    defaultDensity: 1.98,
  },
  NaOH: {
    category: 'deicing',
    name: 'Sodium Hydroxide',
    formula: 'NaOH',
    atoms: 3,
    mw: 40.0,
    elements: ['Na', 'O', 'H'],
    defaultDensity: 2.13,
  },
  Urea: {
    category: 'deicing',
    name: 'Urea',
    formula: 'CH\u2084N\u2082O',
    atoms: 8,
    mw: 60.06,
    elements: ['C', 'H', 'N', 'O'],
    defaultDensity: 1.32,
  },

  // Atmospheric / Aging
  H2O: {
    category: 'atmospheric',
    name: 'Water',
    formula: 'H\u2082O',
    atoms: 3,
    mw: 18.02,
    elements: ['H', 'O'],
    defaultDensity: 1.0,
  },
  CO2: {
    category: 'atmospheric',
    name: 'Carbon Dioxide',
    formula: 'CO\u2082',
    atoms: 3,
    mw: 44.01,
    elements: ['C', 'O'],
    defaultDensity: 0.5,
  },
  O3: {
    category: 'atmospheric',
    name: 'Ozone',
    formula: 'O\u2083',
    atoms: 3,
    mw: 48.0,
    elements: ['O'],
    defaultDensity: 0.5,
  },
  O2: {
    category: 'atmospheric',
    name: 'Oxygen',
    formula: 'O\u2082',
    atoms: 2,
    mw: 32.0,
    elements: ['O'],
    defaultDensity: 0.5,
  },

  // Fuel spills
  nHeptane: {
    category: 'fuel',
    name: 'n-Heptane',
    formula: 'C\u2087H\u2081\u2086',
    atoms: 23,
    mw: 100.21,
    elements: ['C', 'H'],
    defaultDensity: 0.68,
  },
  nHexadecane: {
    category: 'fuel',
    name: 'n-Hexadecane',
    formula: 'C\u2081\u2086H\u2083\u2084',
    atoms: 50,
    mw: 226.44,
    elements: ['C', 'H'],
    defaultDensity: 0.77,
  },
  Toluene: {
    category: 'fuel',
    name: 'Toluene',
    formula: 'C\u2087H\u2088',
    atoms: 15,
    mw: 92.14,
    elements: ['C', 'H'],
    defaultDensity: 0.87,
  },

  // Organic acids
  AceticAcid: {
    category: 'organic_acid',
    name: 'Acetic Acid',
    formula: 'C\u2082H\u2084O\u2082',
    atoms: 8,
    mw: 60.05,
    elements: ['C', 'H', 'O'],
    defaultDensity: 1.05,
  },
  FormicAcid: {
    category: 'organic_acid',
    name: 'Formic Acid',
    formula: 'CH\u2082O\u2082',
    atoms: 5,
    mw: 46.03,
    elements: ['C', 'H', 'O'],
    defaultDensity: 1.22,
  },

  // Solvents
  Methanol: {
    category: 'solvent',
    name: 'Methanol',
    formula: 'CH\u2084O',
    atoms: 6,
    mw: 32.04,
    elements: ['C', 'H', 'O'],
    defaultDensity: 0.79,
  },
  Ethanol: {
    category: 'solvent',
    name: 'Ethanol',
    formula: 'C\u2082H\u2086O',
    atoms: 9,
    mw: 46.07,
    elements: ['C', 'H', 'O'],
    defaultDensity: 0.79,
  },

  // Aging / Corrosive
  H2SO4: {
    category: 'aging',
    name: 'Sulfuric Acid',
    formula: 'H\u2082SO\u2084',
    atoms: 7,
    mw: 98.08,
    elements: ['H', 'S', 'O'],
    defaultDensity: 1.84,
  },
}

export const CATEGORY_LABELS = {
  deicing: 'Deicing Agents',
  atmospheric: 'Atmospheric / Aging',
  fuel: 'Fuel Spills',
  organic_acid: 'Organic Acids',
  solvent: 'Solvents',
  aging: 'Aging / Corrosive',
}

export const CATEGORY_ORDER = ['deicing', 'atmospheric', 'fuel', 'organic_acid', 'solvent', 'aging']

// Batch generation defaults (consistent with crystal structures)
export const BATCH_XY_DEFAULTS = {
  xy_min: 35,
  xy_max: 60,
  lz_default: 10,
}

// Box size presets for interface cells
export const BOX_SIZE_PRESETS = [
  { key: 'small', label: 'Small (30x30x10)', lx: 30, ly: 30, lz: 10 },
  { key: 'medium', label: 'Medium (40x40x10)', lx: 40, ly: 40, lz: 10 },
  { key: 'large', label: 'Large (50x50x15)', lx: 50, ly: 50, lz: 15 },
  { key: 'xlarge', label: 'XL (60x60x20)', lx: 60, ly: 60, lz: 20 },
]

// Calculate molecule count from density and box size
export function calculateMoleculeCount(density, lx, ly, lz, mw) {
  const AVOGADRO = 6.02214076e23
  const volumeA3 = lx * ly * lz
  const totalMassG = density * volumeA3 * 1e-24
  return Math.max(1, Math.round((totalMassG / mw) * AVOGADRO))
}

// Format box dimensions for display
export function formatBoxDimensions(lx, ly, lz) {
  return `${lx.toFixed(0)} x ${ly.toFixed(0)} x ${lz.toFixed(0)} A`
}

// Get default density for a molecule (from config or fallback)
export function getDefaultDensity(molId, apiMolecules = []) {
  // First check API data
  const apiMol = apiMolecules.find((m) => m.mol_id === molId)
  if (apiMol?.default_density) return apiMol.default_density

  // Fallback to config
  const configMol = INTERFACE_MOLECULE_INFO[molId]
  if (configMol?.defaultDensity) return configMol.defaultDensity

  // Default fallback
  return 1.0
}
