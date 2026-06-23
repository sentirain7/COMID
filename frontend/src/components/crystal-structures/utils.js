import { LITERATURE_SIZE_PRESETS } from './config'
import { normalizeElementSymbol } from '../molecule-viewer/elementColors'

export const PREVIEW_ELEMENT_BY_MATERIAL = {
  SiO2: 'Si',
  CaCO3: 'Ca',
  Al2O3: 'Al',
  MgO: 'Mg',
  Fe2O3: 'Fe',
  MgCO3: 'Mg',
  CaO: 'Ca',
  TiO2: 'Ti',
  ZnO: 'Zn',
  NaCl: 'Na',
  KCl: 'K',
  Al: 'Al',
  Fe: 'Fe',
  Cu: 'Cu',
  Ni: 'Ni',
  aggregate: 'Si',
}

export const UNIT_PREVIEW_ELEMENTS_BY_MATERIAL = {
  SiO2: ['Si', 'O'],
  CaCO3: ['Ca', 'C', 'O'],
  Al2O3: ['Al', 'O'],
  MgO: ['Mg', 'O'],
  Fe2O3: ['Fe', 'O'],
  MgCO3: ['Mg', 'C', 'O'],
  CaO: ['Ca', 'O'],
  TiO2: ['Ti', 'O'],
  ZnO: ['Zn', 'O'],
  NaCl: ['Na', 'Cl'],
  KCl: ['K', 'Cl'],
  Al: ['Al'],
  Fe: ['Fe'],
  Cu: ['Cu'],
  Ni: ['Ni'],
  aggregate: ['Si', 'O'],
}

export const STRUCTURE_SIZE_OPTIONS = ['X1', 'X2', 'X3']
export const STRUCTURE_SIZE_AREA_SCALE = {
  X1: 1,
  X2: 2,
  X3: 3,
}
export const DEFAULT_THICKNESS_ANGSTROM = 25
export const ATOMIC_WEIGHTS = {
  H: 1.008,
  C: 12.011,
  N: 14.007,
  O: 15.999,
  Na: 22.989769,
  Mg: 24.305,
  Al: 26.981538,
  Si: 28.085,
  P: 30.973762,
  S: 32.06,
  Cl: 35.45,
  K: 39.0983,
  Ca: 40.078,
  Ti: 47.867,
  Fe: 55.845,
  Ni: 58.6934,
  Cu: 63.546,
  Zn: 65.38,
  Br: 79.904,
  I: 126.90447,
}

export function getScaledXySize(baseXySize, structureSizePreset) {
  const base = Number(baseXySize)
  if (!Number.isFinite(base) || base <= 0) return 1
  const areaScale = Number(STRUCTURE_SIZE_AREA_SCALE[structureSizePreset] || 1)
  return base * Math.sqrt(areaScale)
}

export function findNearestLiteratureXyForMaterial(material, inputValue) {
  const base = LITERATURE_SIZE_PRESETS[material]?.xySize
  const target = Number(inputValue)
  if (!Number.isFinite(base) || base <= 0) return null
  if (!Number.isFinite(target) || target <= 0) {
    const fallback = getScaledXySize(base, 'X1')
    return { sizePreset: 'X1', xyValue: fallback }
  }
  let nearest = null
  let bestDiff = Number.POSITIVE_INFINITY
  for (const sizePreset of STRUCTURE_SIZE_OPTIONS) {
    const candidate = getScaledXySize(base, sizePreset)
    const diff = Math.abs(candidate - target)
    if (diff < bestDiff) {
      bestDiff = diff
      nearest = { sizePreset, xyValue: candidate }
    }
  }
  return nearest
}

export function formatNameNumber(value, fallback = '0') {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  if (Number.isInteger(numeric)) return String(numeric)
  return numeric.toFixed(2).replace(/\.?0+$/, '')
}

export function buildLocalCrystalPreview({
  material,
  nx,
  ny,
  nz,
  xySize,
  thickness,
  hydroxylated,
}) {
  const nxi = Math.max(1, Math.round(Number(nx) || 1))
  const nyi = Math.max(1, Math.round(Number(ny) || 1))
  const nzi = Math.max(1, Math.round(Number(nz) || 1))
  const lx = Math.max(1, Number(xySize) || 1)
  const ly = Math.max(1, Number(xySize) || 1)
  const lz = Math.max(1, Number(thickness) || 1)
  const fallbackElement = PREVIEW_ELEMENT_BY_MATERIAL[material] || 'X'
  const baseAtomTypes = UNIT_PREVIEW_ELEMENTS_BY_MATERIAL[material] || [fallbackElement]

  const maxAtoms = 2500
  const total = nxi * nyi * nzi
  const stride = Math.max(1, Math.ceil(total / maxAtoms))
  const points = []
  const pointMeta = []
  const indexByGrid = new Map()
  let count = 0

  for (let iz = 0; iz < nzi; iz += 1) {
    for (let iy = 0; iy < nyi; iy += 1) {
      for (let ix = 0; ix < nxi; ix += 1) {
        if (count % stride === 0) {
          const x = ((ix + 0.5) / nxi) * lx
          const y = ((iy + 0.5) / nyi) * ly
          const z = ((iz + 0.5) / nzi) * lz
          const atomType = baseAtomTypes[(ix + iy + iz) % baseAtomTypes.length]
          const atomIndex = points.length
          points.push(`${atomType} ${x.toFixed(6)} ${y.toFixed(6)} ${z.toFixed(6)}`)
          pointMeta.push({ ix, iy, iz, atomIndex })
          indexByGrid.set(`${ix}:${iy}:${iz}`, atomIndex)
        }
        count += 1
      }
    }
  }

  const bonds = []
  for (const atom of pointMeta) {
    const nx1 = indexByGrid.get(`${atom.ix + 1}:${atom.iy}:${atom.iz}`)
    const ny1 = indexByGrid.get(`${atom.ix}:${atom.iy + 1}:${atom.iz}`)
    const nz1 = indexByGrid.get(`${atom.ix}:${atom.iy}:${atom.iz + 1}`)
    if (Number.isInteger(nx1)) bonds.push([atom.atomIndex, nx1])
    if (Number.isInteger(ny1)) bonds.push([atom.atomIndex, ny1])
    if (Number.isInteger(nz1)) bonds.push([atom.atomIndex, nz1])
  }

  if (hydroxylated && points.length > 0) {
    const ohCount = Math.min(120, Math.max(8, Math.floor(points.length * 0.15)))
    const topLayer = pointMeta.reduce((acc, atom) => Math.max(acc, atom.iz), 0)
    const topAtoms = pointMeta.filter((atom) => atom.iz === topLayer)
    for (let i = 0; i < ohCount; i += 1) {
      const x = ((i + 0.5) / ohCount) * lx
      const y = (((i * 7) % ohCount) + 0.5) / ohCount * ly
      const oZ = lz + 0.55
      const hZ = lz + 1.15
      const oIndex = points.length
      points.push(`O ${x.toFixed(6)} ${y.toFixed(6)} ${oZ.toFixed(6)}`)
      const hIndex = points.length
      points.push(`H ${x.toFixed(6)} ${y.toFixed(6)} ${hZ.toFixed(6)}`)
      if (topAtoms.length > 0) {
        const anchor = topAtoms[i % topAtoms.length]
        bonds.push([anchor.atomIndex, oIndex])
        bonds.push([oIndex, hIndex])
      }
    }
  }

  return {
    xyz: `${points.length}\nDraft Crystal Preview\n${points.join('\n')}`,
    boxSize: [lx, ly, lz],
    bonds,
    atomCount: points.length,
  }
}

export function buildMaterialUnitPreview(material) {
  const fallbackElement = PREVIEW_ELEMENT_BY_MATERIAL[material] || 'X'
  const atomTypes = UNIT_PREVIEW_ELEMENTS_BY_MATERIAL[material] || [fallbackElement]
  const unit = 6
  const atoms = [
    [0, 0, 0],
    [unit, 0, 0],
    [0, unit, 0],
    [unit, unit, 0],
    [0, 0, unit],
    [unit, 0, unit],
    [0, unit, unit],
    [unit, unit, unit],
  ]
  const points = atoms.map(([x, y, z], index) => {
    const element = atomTypes[index % atomTypes.length]
    return `${element} ${x.toFixed(6)} ${y.toFixed(6)} ${z.toFixed(6)}`
  })
  const bonds = [
    [0, 1], [0, 2], [1, 3], [2, 3],
    [4, 5], [4, 6], [5, 7], [6, 7],
    [0, 4], [1, 5], [2, 6], [3, 7],
  ]

  return {
    xyz: `${points.length}\n${material} minimum unit preview\n${points.join('\n')}`,
    boxSize: [unit, unit, unit],
    bonds,
    atomCount: points.length,
    atomTypes,
  }
}

export function buildCrystalTemplateName({
  material,
  surface,
  thickness,
  xySize,
  hydroxylDensity,
  hydroxylated,
}) {
  const materialToken = String(material || 'material').trim().replace(/\s+/g, '')
  const surfaceToken = String(surface || 'surface').trim().replace(/\s+/g, '')
  const thicknessToken = formatNameNumber(thickness)
  const xyToken = formatNameNumber(xySize)
  const ohToken = formatNameNumber(hydroxylated ? hydroxylDensity : 0)
  return `${materialToken}-${surfaceToken}-th${thicknessToken}-xy${xyToken}-oh${ohToken}`
}

export function formatCellMetrics(boxSize) {
  if (!Array.isArray(boxSize) || boxSize.length < 3) {
    return { lx: null, ly: null, lz: null, volume: null }
  }
  const lx = Number(boxSize[0])
  const ly = Number(boxSize[1])
  const lz = Number(boxSize[2])
  if (![lx, ly, lz].every((v) => Number.isFinite(v))) {
    return { lx: null, ly: null, lz: null, volume: null }
  }
  return {
    lx,
    ly,
    lz,
    volume: lx * ly * lz,
  }
}

export function formatTransformationMatrix(matrix) {
  if (!Array.isArray(matrix) || matrix.length !== 2) return null
  const [[p, q], [r, s]] = matrix
  if (![p, q, r, s].every(Number.isFinite)) return null
  return q === 0 && r === 0 ? `${p}x${s}` : `[[${p},${q}],[${r},${s}]]`
}

export function formatErrorPct(pct) {
  const numeric = Number(pct)
  if (!Number.isFinite(numeric)) return '-'
  return `${numeric.toFixed(1)}%`
}

export function extractAtomStatsFromXyz(xyzData, volumeA3) {
  if (!xyzData) {
    return {
      counts: {},
      totalAtoms: 0,
      densityGcm3: null,
      massAmu: 0,
      numberDensityNm3: null,
      uniqueTypes: 0,
    }
  }
  const lines = String(xyzData).split('\n')
  const nAtoms = Number.parseInt(lines[0], 10)
  if (!Number.isFinite(nAtoms) || nAtoms <= 0) {
    return {
      counts: {},
      totalAtoms: 0,
      densityGcm3: null,
      massAmu: 0,
      numberDensityNm3: null,
      uniqueTypes: 0,
    }
  }
  const counts = {}
  for (let i = 2; i < 2 + nAtoms && i < lines.length; i += 1) {
    const symbol = normalizeElementSymbol(lines[i].trim().split(/\s+/)[0])
    if (!symbol) continue
    counts[symbol] = (counts[symbol] || 0) + 1
  }
  let massAmu = 0
  for (const [symbol, count] of Object.entries(counts)) {
    const w = Number(ATOMIC_WEIGHTS[symbol] || 0)
    massAmu += w * Number(count)
  }
  const densityGcm3 =
    Number.isFinite(volumeA3) && volumeA3 > 0 && massAmu > 0
      ? (massAmu * 1.6605390666) / volumeA3
      : null
  const numberDensityNm3 =
    Number.isFinite(volumeA3) && volumeA3 > 0
      ? nAtoms / (volumeA3 * 1e-3)
      : null
  return {
    counts,
    totalAtoms: nAtoms,
    densityGcm3,
    massAmu,
    numberDensityNm3,
    uniqueTypes: Object.keys(counts).length,
  }
}

export function buildFormulaFromCounts(counts) {
  const entries = Object.entries(counts || {}).filter(([, value]) => Number(value) > 0)
  if (!entries.length) return '-'
  const hasC = entries.some(([symbol]) => symbol === 'C')
  const hasH = entries.some(([symbol]) => symbol === 'H')
  const ordered = []
  if (hasC) ordered.push(...entries.filter(([symbol]) => symbol === 'C'))
  if (hasH) ordered.push(...entries.filter(([symbol]) => symbol === 'H'))
  ordered.push(...entries.filter(([symbol]) => symbol !== 'C' && symbol !== 'H').sort(([a], [b]) => a.localeCompare(b)))
  return ordered.map(([symbol, count]) => `${symbol}${Number(count) > 1 ? count : ''}`).join('')
}
