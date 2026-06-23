export const TARGET_OPTIONS = [
  'density',
  'cohesive_energy_density',
  'viscosity',
  'msd_diffusion_coefficient',
  'adhesion_energy',
  'rdf_first_peak_r',
  'rdf_first_peak_g',
  'orientation_order',
  'tensile_strength',
  'elastic_modulus',
  'interfacial_tensile_strength',
  'e_inter_interface_1',
  'work_of_separation',
]

export function parseMetricsJson(raw) {
  if (!raw) return null
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return parsed
  } catch {
    return null
  }
}
