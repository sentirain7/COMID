/**
 * Shared 3D scatter plot building blocks.
 *
 * Extracted from BinderPropertyViews to allow reuse across Analysis tabs
 * (bulk property scatter, layered-structure scatter, GHG scatter) without
 * duplicating axis/point/canvas logic.
 */

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { OrbitControls, Text, Line } from '@react-three/drei'
import * as THREE from 'three'
import { ANALYSIS_BG } from '../../lib/constants'

// ─── 3D Axis Lines (origin at grid corner) ──────────────────────────────────
export function AxisLines({ size = 8, labels = {} }) {
  const axisColor = ANALYSIS_BG.textMuted || '#8b949e'
  const tipOffset = 0.6
  return (
    <>
      {/* X axis (red) — along grid bottom edge */}
      <Line points={[[-size, 0, -size], [size, 0, -size]]} color="#ef4444" lineWidth={1.5} />
      <mesh position={[size + tipOffset, 0, -size]} rotation={[0, 0, -Math.PI / 2]}>
        <coneGeometry args={[0.12, 0.4, 8]} />
        <meshBasicMaterial color="#ef4444" />
      </mesh>
      <Text position={[size + 1.2, 0, -size]} fontSize={0.38} color={axisColor} anchorX="left">
        {labels.x || 'X'}
      </Text>

      {/* Y axis (green) — up from grid corner */}
      <Line points={[[-size, 0, -size], [-size, size, -size]]} color="#22c55e" lineWidth={1.5} />
      <mesh position={[-size, size + tipOffset, -size]} rotation={[0, 0, 0]}>
        <coneGeometry args={[0.12, 0.4, 8]} />
        <meshBasicMaterial color="#22c55e" />
      </mesh>
      <Text position={[-size, size + 1.2, -size]} fontSize={0.38} color={axisColor} anchorX="center">
        {labels.y || 'Y'}
      </Text>

      {/* Z axis (blue) — along grid bottom edge */}
      <Line points={[[-size, 0, -size], [-size, 0, size]]} color="#3b82f6" lineWidth={1.5} />
      <mesh position={[-size, 0, size + tipOffset]} rotation={[Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.12, 0.4, 8]} />
        <meshBasicMaterial color="#3b82f6" />
      </mesh>
      <Text position={[-size, 0, size + 1.2]} fontSize={0.38} color={axisColor} anchorX="center">
        {labels.z || 'Z'}
      </Text>
    </>
  )
}

// ─── Scatter Point ──────────────────────────────────────────────────────────
export function ScatterPoint({ item, isHovered, onHover, color }) {
  const groupRef = useRef(null)

  useFrame(() => {
    if (!groupRef.current) return
    const nextScale = isHovered ? 1.4 : 1
    groupRef.current.scale.lerp(new THREE.Vector3(nextScale, nextScale, nextScale), 0.18)
  })

  return (
    <group
      ref={groupRef}
      position={item.position}
      onPointerOver={(e) => {
        e.stopPropagation()
        onHover(item)
      }}
      onPointerOut={() => onHover(null)}
    >
      <mesh>
        <sphereGeometry args={[0.22, 18, 18]} />
        <meshStandardMaterial color={color} />
      </mesh>
    </group>
  )
}

// ─── Scatter Canvas Wrapper ─────────────────────────────────────────────────
export function ScatterCanvas({ children }) {
  return (
    <>
      <ambientLight intensity={0.75} />
      <pointLight position={[10, 14, 8]} intensity={1.2} />
      {children}
      <gridHelper args={[16, 16, ANALYSIS_BG.grid, ANALYSIS_BG.gridSub]} />
      <OrbitControls enablePan enableZoom enableRotate minDistance={6} maxDistance={36} />
    </>
  )
}

// ─── Category Tick Labels ───────────────────────────────────────────────────
// Renders category labels along an axis for categorical data on 3D scatter.
export function CategoryTickLabels({ categories, axis = 'x', size = 8 }) {
  const axisColor = ANALYSIS_BG.textMuted || '#8b949e'
  if (!categories?.length) return null

  const span = size * 2
  return (
    <>
      {categories.map((cat, i) => {
        const t = categories.length > 1 ? (i / (categories.length - 1)) * span - size : 0
        const pos =
          axis === 'x' ? [t, -0.5, -size] :
          axis === 'z' ? [-size, -0.5, t] :
          [-size - 0.8, t, -size]
        return (
          <Text
            key={cat}
            position={pos}
            fontSize={0.28}
            color={axisColor}
            anchorX="center"
            anchorY="top"
            rotation={axis === 'x' ? [-Math.PI / 6, 0, 0] : axis === 'z' ? [-Math.PI / 6, Math.PI / 4, 0] : [0, 0, 0]}
          >
            {cat}
          </Text>
        )
      })}
    </>
  )
}
