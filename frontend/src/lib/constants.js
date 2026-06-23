export const STRUCTURE_SIZE_OPTIONS = ['X1', 'X2', 'X3']

export const AGING_STATE_OPTIONS = [
  { value: 'non_aging', label: 'None' },
  { value: 'short_aging', label: 'Short' },
  { value: 'long_aging', label: 'Long' },
]

// GAFF2 is the only active organic submission track (ReaxFF submission unused, v01.05.58).
// The submission screen does not let the user select an FF; it auto-applies and labels it
// based on composition (AppliedForceFieldNote).
export const FF_OPTIONS = [{ value: 'bulk_ff_gaff2', label: 'GAFF2' }]

/** Look up FF display label from FF_OPTIONS by value. */
export function getFFLabel(ffType) {
  return FF_OPTIONS.find((o) => o.value === ffType)?.label || ffType
}

export const FALLBACK_BINDER_TYPES = [
  { name: 'AAA1', description: 'AAA-1 asphalt binder (default)', sara_fractions: {} },
  { name: 'AAK1', description: 'AAK-1 asphalt binder', sara_fractions: {} },
  { name: 'AAM1', description: 'AAM-1 asphalt binder', sara_fractions: {} },
]

export const FALLBACK_BINDER_TYPE_NAMES = FALLBACK_BINDER_TYPES.map((binder) => binder.name)

export { SARA_COLORS, ADDITIVE_COLORS, BINDER_COLORS, THERMO_COLORS, TIER_COLORS, CRYSTAL_COLORS, LAYER_TYPE_COLORS } from './colorPresets'
export { ANALYSIS_BG, ANALYSIS_SARA, ANALYSIS_ADDITIVE, ANALYSIS_BINDER, ANALYSIS_CRYSTAL, ANALYSIS_LAYER_TYPE } from './colorPresets'

export const CATEGORY_BADGE_STYLES = {
  saturate: 'bg-green-500/20 text-green-400 border-green-500/30',
  aromatic: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  resin: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  asphaltene: 'bg-red-500/20 text-red-400 border-red-500/30',
  additive: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  // Single moles categories
  atmospheric: 'bg-sky-500/20 text-sky-400 border-sky-500/30',
  fuel: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  solvent: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
  organic_acid: 'bg-lime-500/20 text-lime-400 border-lime-500/30',
  deicing: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  aging: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  inorganic_acid: 'bg-red-600/20 text-red-500 border-red-600/30',  // v01.02.07
  // Additive categories
  inorganic: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  polymer: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  organic_polymer: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  chemical: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  organic_wax: 'bg-yellow-600/20 text-yellow-500 border-yellow-600/30',
  recycled_polymer: 'bg-emerald-600/20 text-emerald-500 border-emerald-600/30',
  surfactant: 'bg-fuchsia-500/20 text-fuchsia-400 border-fuchsia-500/30',
  nanoparticle: 'bg-blue-600/20 text-blue-500 border-blue-600/30',
}

// Text-only category colors derived from CATEGORY_BADGE_STYLES (SSOT).
// Extracts the `text-*` class from each badge style string.
export const CATEGORY_TEXT_COLORS = Object.fromEntries(
  Object.entries(CATEGORY_BADGE_STYLES).map(([key, classes]) => {
    const textClass = classes.split(' ').find((c) => c.startsWith('text-')) || 'text-slate-400'
    return [key, textClass]
  })
)

export const AGING_BADGE_STYLES = {
  non_aging: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  short_aging: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  long_aging: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
}

export const AGING_BADGE_LABELS = {
  non_aging: 'U (Virgin)',
  short_aging: 'S (RTFOT)',
  long_aging: 'L (PAV)',
}

export const SARA_TEXT_COLORS = {
  saturate: 'text-green-300',
  aromatic: 'text-yellow-300',
  resin: 'text-orange-300',
  asphaltene: 'text-red-300',
}

// CANDIDATE_ORIGIN_COLORS: retained for the reusable shared CandidateCard
// (recommendation/candidate badge), slated for the inverse-design wizard.
export const CANDIDATE_ORIGIN_COLORS = {
  db: 'bg-emerald-800 text-emerald-200',
  literature: 'bg-blue-800 text-blue-200',
  web: 'bg-amber-800 text-amber-200',
  ml: 'bg-violet-800 text-violet-200',
}

export const ADDITIVE_TYPE_LABELS = {
  SBS: 'SBS Polymer',
  PPA: 'Polyphosphoric Acid',
  Elvaloy: 'Elvaloy',
  Sasobit: 'Sasobit Wax',
  NanoClay: 'Nanoclay',
  CRM: 'Crumb Rubber',
}

export const AGENT_MODE_STYLES = {
  mock: { label: 'Mock', color: 'bg-slate-600 text-slate-200', description: 'All heuristic adapters' },
  hybrid: { label: 'Hybrid', color: 'bg-blue-700 text-blue-200', description: 'Real weather + heuristic others' },
  real: { label: 'Real', color: 'bg-emerald-700 text-emerald-200', description: 'All real adapters' },
}

// Binder abbreviation mapping (SSOT — matches backend pathing.py)
export const BINDER_ABBREV = {
  AAA1: 'A1',
  AAK1: 'K1',
  AAM1: 'M1',
}

// Aging state abbreviation mapping (SSOT — matches backend pathing.py)
export const AGING_ABBREV = {
  non_aging: 'NA',
  short_aging: 'SA',
  long_aging: 'LA',
}

export const BINDER_ANALYSIS_STATE_COLORS = {
  intake: 'bg-amber-800 text-amber-200',
  clarifying: 'bg-cyan-800 text-cyan-200',
  planning: 'bg-blue-800 text-blue-200',
  awaiting_confirmation: 'bg-indigo-800 text-indigo-200',
  executing: 'bg-purple-800 text-purple-200',
  completed: 'bg-emerald-800 text-emerald-200',
  failed: 'bg-red-800 text-red-200',
}

export const BINDER_ANALYSIS_STATE_LABELS = {
  intake: 'Intake',
  clarifying: 'Clarifying',
  planning: 'Planning',
  awaiting_confirmation: 'Awaiting Confirmation',
  executing: 'Executing',
  completed: 'Completed',
  failed: 'Failed',
}

export const INTENT_KIND_LABELS = {
  bulk_property: 'Bulk Property',
  interface_adhesion: 'Interface Adhesion',
  moisture_effect: 'Moisture Effect',
  direct_tensile: 'Direct Tensile',
  internal_cohesion: 'Internal Cohesion',
  aging_comparison: 'Aging Comparison',
}

export const INTENT_KIND_ICONS = {
  bulk_property: 'Beaker',
  interface_adhesion: 'Layers',
  moisture_effect: 'Droplets',
  direct_tensile: 'ArrowUpDown',
  internal_cohesion: 'Link2',
  aging_comparison: 'Clock',
}

// Aging colors for analysis charts (distinct from badge styles)
export const AGING_ANALYSIS_COLORS = {
  non_aging: '#60a5fa',
  short_aging: '#f59e0b',
  long_aging: '#f43f5e',
}

export const AGING_ANALYSIS_LABELS = {
  non_aging: 'NA (Virgin)',
  short_aging: 'SA (RTFOT)',
  long_aging: 'LA (PAV)',
}

export const SCATTER3D_AXIS_OPTIONS = [
  { value: 'density', label: 'Density (g/cm\u00B3)' },
  { value: 'cohesive_energy_density', label: 'CED (MJ/m\u00B3)' },
  { value: 'elastic_modulus', label: 'Elastic Modulus (GPa)' },
  { value: 'bulk_modulus', label: 'Bulk Modulus (GPa)' },
  { value: 'viscosity', label: 'Viscosity (mPa\u00B7s)' },
  { value: 'tensile_strength', label: 'Tensile Strength (MPa)' },
  { value: 'adhesion_energy', label: 'Adhesion Energy (mJ/m\u00B2)' },
  { value: 'glass_transition_temperature_k', label: 'Tg (K)' },
]

export const LAYERED_3D_AXIS_OPTIONS = [
  // Continuous (metrics)
  { value: 'adhesion_energy', label: 'Adhesion Energy (mJ/m\u00B2)', type: 'continuous' },
  { value: 'tensile_strength', label: 'Tensile Strength (MPa)', type: 'continuous' },
  { value: 'elastic_modulus', label: 'Elastic Modulus (GPa)', type: 'continuous' },
  { value: 'toughness', label: 'Toughness (MJ/m\u00B3)', type: 'continuous' },
  { value: 'work_of_separation', label: 'W_sep (mJ/m\u00B2)', type: 'continuous' },
  { value: 'ductility', label: 'Ductility', type: 'continuous' },
  { value: 'orientation_order', label: 'Orientation Order', type: 'continuous' },
  { value: 'e_inter_interface_1', label: 'E_inter (kcal/mol)', type: 'continuous' },
  { value: 'ghg_emission', label: 'GHG (kgCO\u2082e/kg)', type: 'continuous' },
  { value: 'temperature_K', label: 'Temperature (K)', type: 'continuous' },
  // Categorical (variables)
  { value: 'crystal_material', label: 'Crystal Material', type: 'categorical' },
  { value: 'layer_type', label: 'Layer Configuration', type: 'categorical' },
  { value: 'aging_state', label: 'Aging State', type: 'categorical' },
  { value: 'binder_type', label: 'Binder Type', type: 'categorical' },
  { value: 'has_water', label: 'Moisture', type: 'categorical' },
]

export const LAYERED_COLOR_BY_OPTIONS = [
  { value: 'layer_type', label: 'Layer Config' },
  { value: 'crystal_material', label: 'Crystal' },
  { value: 'aging_state', label: 'Aging' },
  { value: 'binder_type', label: 'Binder' },
  { value: 'has_water', label: 'Moisture' },
]

export const CURVE_METRIC_TABS = [
  { key: 'rdf_curve', label: 'RDF (All)', enabled: true },
  { key: 'rdf_pair_curve', label: 'RDF (Pairs)', enabled: true },
  { key: 'msd_curve', label: 'MSD', enabled: true },
  { key: 'cohesive_energy_density_profile', label: 'CED Profile', enabled: true },
  { key: 'density_profile', label: 'Density Profile', enabled: false },
  { key: 'thermo_log', label: 'Thermo Log', enabled: true },
]

export const LAYER_TYPE_LABELS = {
  'interface': 'Crystal + Binder',
  'water-interface': 'Crystal + Water + Binder',
  '3-layer': 'Crystal + Binder + Crystal',
  'aged-fresh': 'Crystal + Aged + Fresh',
  'water-aged-fresh': 'Crystal + Water + Aged + Fresh',
  'binder-binder': 'Binder + Binder',
}

// ── Inverse Design Pipeline (wizard ①~④) ──────────────────────────────
// Metric choices exposed as inverse-design targets. The definition SSOT is the
// backend contracts/policies/metrics.py — here we only handle the UI choices/unit display.
export const INVERSE_TARGET_METRICS = [
  { name: 'density', label: 'Density', unit: 'g/cm3', group: 'Bulk' },
  { name: 'viscosity', label: 'Viscosity', unit: 'mPa·s', group: 'Bulk' },
  { name: 'cohesive_energy_density', label: 'Cohesive Energy Density', unit: 'MJ/m³', group: 'Bulk' },
  { name: 'bulk_modulus', label: 'Bulk Modulus', unit: 'GPa', group: 'Bulk' },
  { name: 'glass_transition_temperature_k', label: 'Glass Transition (Tg)', unit: 'K', group: 'Bulk' },
  { name: 'work_of_separation', label: 'Work of Separation', unit: 'mJ/m²', group: 'Interface' },
  { name: 'interfacial_tensile_strength', label: 'Interfacial Tensile Strength', unit: 'MPa', group: 'Interface' },
]

export const INVERSE_TARGET_DIRECTIONS = [
  { value: 'maximize', label: 'Maximize' },
  { value: 'minimize', label: 'Minimize' },
  { value: 'target', label: 'Target range' },
]

// Aggregate (crystal) choices for interface targets — a representative subset of the
// same material family as the crystal builder.
export const INVERSE_AGGREGATE_MATERIALS = ['SiO2', 'CaCO3', 'Al2O3', 'MgO', 'Fe2O3']

export const PIPELINE_MODE_BADGES = {
  bootstrap: { label: 'BOOTSTRAP (DOE seed)', className: 'bg-amber-500/20 text-amber-300' },
  bo: { label: 'BO (Bayesian design)', className: 'bg-emerald-500/20 text-emerald-300' },
}
