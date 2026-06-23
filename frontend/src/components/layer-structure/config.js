export const SOURCE_TYPE_OPTIONS = [
  { value: 'binder_cell', label: 'Binder Cell' },
  { value: 'interface_molecule_cell', label: 'Interface Molecule Cell' },
  { value: 'crystal_structure', label: 'Crystal Structure' },
]

// Layered structures always use p p f:
// x,y periodic (infinite lateral extent), z fixed (free surfaces / interfaces).
// p p p is physically inappropriate for layer stacks (z-periodic images overlap).
export const LAYER_BOUNDARY_MODE = 'ppf'

export const LAYER_REQUIRED_STAGES = ['minimize', 'nvt_equilibration', 'npt_equilibration']
export const LAYER_OPTIONAL_STAGES = ['high_temp_nvt', 'annealing_cycles']
export const LAYER_CORE_STAGES = [...LAYER_REQUIRED_STAGES, ...LAYER_OPTIONAL_STAGES]
export const LAYER_STAGES = [
  ...LAYER_CORE_STAGES, 'tensile_pull'
]

export const SECTION_TITLE_CLASS = 'text-sm font-semibold mb-1'

// XY mismatch tolerances (% of reference XY)
export const XY_WARN_PCT = 5    // <=5% -> pass (green), >5% -> warn (amber)
export const XY_FAIL_PCT = 12   // >12% -> fail (red)
