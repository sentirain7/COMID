import { useState, useMemo } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { ANALYSIS_BG, ANALYSIS_BINDER, AGING_ANALYSIS_COLORS, AGING_ANALYSIS_LABELS } from '../../lib/constants'
import { getAnalysisAdditiveColor } from '../../lib/colorPresets'
import useThemeVersion from '../../hooks/useThemeVersion'
import { AxisLines, ScatterPoint } from './ScatterPrimitives'

// ─── Color-by toggle options ─────────────────────────────────────────────────
const COLOR_BY_OPTIONS = [
  { value: 'additive', label: 'Additive' },
  { value: 'binder', label: 'Binder' },
  { value: 'aging', label: 'Aging' },
]

/** Get point color based on selected colorBy property */
function getPointColor(item, colorBy) {
  switch (colorBy) {
    case 'binder':
      return ANALYSIS_BINDER[item.binder_type] || ANALYSIS_BINDER.unknown || '#888888'
    case 'aging':
      return AGING_ANALYSIS_COLORS[item.aging_state] || AGING_ANALYSIS_COLORS.non_aging
    case 'additive':
    default:
      return getAnalysisAdditiveColor(item.additive || 'none')
  }
}

// ─── Scatter Scene (Method A) ───────────────────────────────────────────────
function ScatterScene({ points, hovered, onHover, axisLabels = {}, colorBy = 'additive' }) {
  return (
    <>
      <ambientLight intensity={0.75} />
      <pointLight position={[10, 14, 8]} intensity={1.2} />
      {points.map((item) => (
        <ScatterPoint
          key={item.exp_id || item.mol_id}
          item={item}
          isHovered={hovered?.exp_id === item.exp_id}
          onHover={onHover}
          color={getPointColor(item, colorBy)}
        />
      ))}
      <AxisLines labels={{
        x: axisLabels?.x || 'Temperature (K)',
        y: axisLabels?.y || 'Density (g/cm\u00B3)',
        z: axisLabels?.z || 'CED (MJ/m\u00B3)',
      }} />
      <gridHelper args={[16, 16, ANALYSIS_BG.grid, ANALYSIS_BG.gridSub]} />
      <OrbitControls enablePan enableZoom enableRotate minDistance={6} maxDistance={36} />
    </>
  )
}

// ─── Column (Method B) ──────────────────────────────────────────────────────
function Column({ col }) {
  return (
    <group position={[col.x, col.height / 2, col.z]}>
      <mesh>
        <boxGeometry args={[0.85, col.height, 0.85]} />
        <meshStandardMaterial color={col.color} metalness={0.2} roughness={0.5} />
      </mesh>
    </group>
  )
}

// ─── Column Scene (Method B) ────────────────────────────────────────────────
function ColumnScene({ columns }) {
  return (
    <>
      <ambientLight intensity={0.75} />
      <pointLight position={[12, 12, 12]} intensity={1.1} />
      {columns.map((col) => (
        <Column key={col.id} col={col} />
      ))}
      <AxisLines labels={{
        x: 'Temperature Bin',
        y: 'Avg CED',
        z: 'Density Bin',
      }} />
      <gridHelper args={[16, 16, ANALYSIS_BG.grid, ANALYSIS_BG.gridSub]} />
      <OrbitControls enablePan enableZoom enableRotate minDistance={7} maxDistance={42} />
    </>
  )
}

// ─── Build binned columns ───────────────────────────────────────────────────
function buildColumns(points, colorBy) {
  if (!Array.isArray(points) || points.length === 0) return []

  const temps = points.map((p) => Number(p.temperature_k) || 0)
  const densities = points.map((p) => Number(p.density) || 0)
  const ceds = points.map((p) => Number(p.ced) || 0)
  const tempMin = Math.min(...temps)
  const tempMax = Math.max(...temps)
  const denMin = Math.min(...densities)
  const denMax = Math.max(...densities)
  const cedMin = Math.min(...ceds)
  const cedMax = Math.max(...ceds)

  const tempBinCount = 8
  const denBinCount = 8
  const bins = new Map()

  const toBin = (value, low, high, count) => {
    if (high <= low) return 0
    const ratio = (value - low) / (high - low)
    return Math.max(0, Math.min(count - 1, Math.floor(ratio * count)))
  }

  points.forEach((p) => {
    const tBin = toBin(Number(p.temperature_k) || 0, tempMin, tempMax, tempBinCount)
    const dBin = toBin(Number(p.density) || 0, denMin, denMax, denBinCount)
    const key = `${tBin}:${dBin}`
    const row = bins.get(key) || {
      ceds: [],
      binderCount: {},
      additiveCount: {},
      agingCount: {},
    }
    row.ceds.push(Number(p.ced) || 0)
    const binder = String(p.binder_type || 'unknown')
    const additive = String(p.additive || 'none')
    const aging = String(p.aging_state || 'non_aging')
    row.binderCount[binder] = (row.binderCount[binder] || 0) + 1
    row.additiveCount[additive] = (row.additiveCount[additive] || 0) + 1
    row.agingCount[aging] = (row.agingCount[aging] || 0) + 1
    bins.set(key, row)
  })

  const dominant = (counts) =>
    Object.entries(counts).sort((a, b) => Number(b[1]) - Number(a[1]))[0]?.[0] || 'unknown'

  const columns = []
  bins.forEach((row, key) => {
    const [tBin, dBin] = key.split(':').map(Number)
    const avgCed = row.ceds.reduce((acc, x) => acc + x, 0) / Math.max(row.ceds.length, 1)
    const cedRatio = cedMax > cedMin ? (avgCed - cedMin) / (cedMax - cedMin) : 0.5
    const height = 0.4 + cedRatio * 4.8
    const domBinder = dominant(row.binderCount)
    const domAdditive = dominant(row.additiveCount)
    const domAging = dominant(row.agingCount)
    columns.push({
      id: key,
      x: -7 + tBin * 2,
      z: -7 + dBin * 2,
      height,
      color: getPointColor(
        { binder_type: domBinder, additive: domAdditive, aging_state: domAging },
        colorBy,
      ),
    })
  })

  return columns
}

export { ScatterScene, ScatterPoint }

export default function BinderPropertyViews({ points, hovered, onHover }) {
  const themeVer = useThemeVersion('analysis')
  const [colorBy, setColorBy] = useState('additive')
  // themeVer triggers re-computation when color preset changes (used by buildColumns indirectly)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const columns = useMemo(() => buildColumns(points, colorBy), [points, colorBy, themeVer])

  // Dynamic legend items based on colorBy
  const legendItems = useMemo(() => {
    if (colorBy === 'binder') {
      const seen = new Set()
      points.forEach(p => { if (p.binder_type) seen.add(p.binder_type) })
      return [...seen].sort().map(name => ({
        name,
        color: ANALYSIS_BINDER[name] || ANALYSIS_BINDER.unknown || '#888',
      }))
    }
    if (colorBy === 'aging') {
      const seen = new Set()
      points.forEach(p => { if (p.aging_state) seen.add(p.aging_state) })
      return [...seen].sort().map(state => ({
        name: AGING_ANALYSIS_LABELS[state] || state,
        color: AGING_ANALYSIS_COLORS[state] || '#888',
      }))
    }
    // additive (default)
    const map = {}
    points.forEach(p => {
      const key = String(p.additive || 'none')
      map[key] = (map[key] || 0) + 1
    })
    return Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name]) => ({
        name,
        color: getAnalysisAdditiveColor(name),
      }))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, colorBy, themeVer])

  return (
    <div className="space-y-3">
      {/* Color-by toggle buttons */}
      <div className="flex items-center gap-2">
        <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>Color by:</span>
        {COLOR_BY_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => setColorBy(opt.value)}
            className={`px-3 py-1 rounded text-xs border transition-colors ${
              colorBy === opt.value
                ? 'bg-cyan-500/20 border-cyan-400/50 text-cyan-300'
                : 'hover:brightness-125'
            }`}
            style={colorBy !== opt.value ? { backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.textMuted } : {}}
          >
            {opt.label}
          </button>
        ))}
        {/* Legend inline */}
        <span className="ml-3 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>|</span>
        {legendItems.map(item => (
          <span key={item.name} className="inline-flex items-center gap-1 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
            {item.name}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="relative h-[420px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
          <div className="absolute top-3 left-3 z-10 text-xs px-2 py-1 rounded" style={{ color: ANALYSIS_BG.text, backgroundColor: ANALYSIS_BG.overlay }}>
            Method A: Experiment Point Cloud
          </div>
          <Canvas camera={{ position: [11, 10, 11], fov: 50 }}>
            <ScatterScene points={points} hovered={hovered} onHover={onHover} colorBy={colorBy} />
          </Canvas>
        </div>

        <div className="relative h-[420px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
          <div className="absolute top-3 left-3 z-10 text-xs px-2 py-1 rounded" style={{ color: ANALYSIS_BG.text, backgroundColor: ANALYSIS_BG.overlay }}>
            Method B: Binned CED Volume Columns
          </div>
          <Canvas camera={{ position: [12, 12, 12], fov: 50 }}>
            <ColumnScene columns={columns} />
          </Canvas>
        </div>
      </div>
    </div>
  )
}
