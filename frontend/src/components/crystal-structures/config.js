export const MATERIAL_OPTIONS = [
  'SiO2',
  'CaCO3',
  'Al2O3',
  'MgO',
  'Fe2O3',
  'MgCO3',
  'CaO',
  'TiO2',
  'ZnO',
  'NaCl',
  'KCl',
  'Al',
  'Fe',
  'Cu',
  'Ni',
  'aggregate',
]

export const PRESET_MATERIAL_OPTIONS = [
  'SiO2',
  'CaCO3',
  'Al2O3',
  'MgO',
  'Fe2O3',
  'MgCO3',
  'CaO',
  'TiO2',
  'ZnO',
  'NaCl',
  'KCl',
  'Al',
  'Fe',
  'Cu',
  'Ni',
]

export const SURFACE_OPTIONS = ['001', '010', '100', '110', '111']

export const LITERATURE_SIZE_PRESETS = {
  SiO2: {
    thickness: 17.2,
    xySize: 38.618,
    nx: 6,
    ny: 7,
    nz: 2,
    ref: 'Buildings 2025, 15(23), 4384 (Table 2) + FSCE 2020 14(7):810-822',
  },
  CaCO3: {
    thickness: 17.2,
    xySize: 39.206,
    nx: 6,
    ny: 7,
    nz: 2,
    ref: 'Buildings 2025, 15(23), 4384 (Table 2)',
  },
  Al2O3: {
    thickness: 17.2,
    xySize: 38.002,
    nx: 6,
    ny: 7,
    nz: 2,
    ref: 'Buildings 2025, 15(23), 4384 (Table 2)',
  },
  MgO: {
    thickness: 17.2,
    xySize: 37.917,
    nx: 9,
    ny: 9,
    nz: 4,
    ref: 'Case Studies in Construction Materials 2022, DOI: 10.1016/j.cscm.2022.e01581',
  },
  Fe2O3: {
    thickness: 17.2,
    xySize: 39.236,
    nx: 7,
    ny: 9,
    nz: 1,
    ref: 'Case Studies in Construction Materials 2022, DOI: 10.1016/j.cscm.2022.e01581',
  },
  MgCO3: {
    thickness: 17.2,
    xySize: 40.120,
    nx: 8,
    ny: 10,
    nz: 1,
    ref: 'Construction and Building Materials 2024, DOI: 10.1016/j.conbuildmat.2024.135923',
  },
  CaO: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 8,
    ny: 8,
    nz: 4,
    ref: 'Extended engineering preset',
  },
  TiO2: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 8,
    ny: 8,
    nz: 6,
    ref: 'Extended engineering preset',
  },
  ZnO: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 9,
    ny: 10,
    nz: 4,
    ref: 'Extended engineering preset',
  },
  NaCl: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 8,
    ny: 8,
    nz: 4,
    ref: 'Extended engineering preset',
  },
  KCl: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 7,
    ny: 7,
    nz: 3,
    ref: 'Extended engineering preset',
  },
  Al: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 10,
    ny: 10,
    nz: 5,
    ref: 'Extended engineering preset',
  },
  Fe: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 14,
    ny: 14,
    nz: 6,
    ref: 'Extended engineering preset',
  },
  Cu: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 12,
    ny: 12,
    nz: 5,
    ref: 'Extended engineering preset',
  },
  Ni: {
    thickness: 17.2,
    xySize: 40.0,
    nx: 12,
    ny: 12,
    nz: 5,
    ref: 'Extended engineering preset',
  },
  aggregate: {
    thickness: 17.2,
    xySize: 38.618,
    nx: 6,
    ny: 7,
    nz: 2,
    ref: 'Buildings 2025, 15(23), 4384 (Table 2)',
  },
}

export const LITERATURE_CRYSTAL_SET = [
  {
    key: 'lit_quartz_001',
    name: 'LIT-Quartz-001',
    material: 'SiO2',
    surface: '001',
    ...LITERATURE_SIZE_PRESETS.SiO2,
  },
  {
    key: 'lit_calcite_001',
    name: 'LIT-Calcite-001',
    material: 'CaCO3',
    surface: '001',
    ...LITERATURE_SIZE_PRESETS.CaCO3,
  },
  {
    key: 'lit_alumina_001',
    name: 'LIT-Alumina-001',
    material: 'Al2O3',
    surface: '001',
    ...LITERATURE_SIZE_PRESETS.Al2O3,
  },
  {
    key: 'lit_mgo_001',
    name: 'LIT-MgO-001',
    material: 'MgO',
    surface: '001',
    ...LITERATURE_SIZE_PRESETS.MgO,
  },
  {
    key: 'lit_hematite_001',
    name: 'LIT-Hematite-001',
    material: 'Fe2O3',
    surface: '001',
    ...LITERATURE_SIZE_PRESETS.Fe2O3,
  },
  {
    key: 'lit_magnesite_001',
    name: 'LIT-Magnesite-001',
    material: 'MgCO3',
    surface: '001',
    ...LITERATURE_SIZE_PRESETS.MgCO3,
  },
]

export const formatSizeAngstrom = (value) => {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(1) : '-'
}

export const formatArtifactLabel = (pathValue) => {
  if (!pathValue) return '-'
  const normalized = String(pathValue).replace(/\\/g, '/')
  const parts = normalized.split('/')
  return parts[parts.length - 1] || normalized
}
