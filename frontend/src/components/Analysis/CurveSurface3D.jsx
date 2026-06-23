import { useMemo, useState, Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Text, Line } from '@react-three/drei'
import { ANALYSIS_BG } from '../../lib/constants'
import { getChartColorByIndex } from '../../lib/chartUtils'
import { AxisLines } from './ScatterPrimitives'

const GRID_SIZE = 8

/**
 * 3D stacked polyline visualization for curve data.
 *
 * X = metric x-axis (r or time_ps), Y = temperature (stacked per experiment), Z = metric value (g_r or msd)
 *
 * Props:
 *   experiments: [{ expId, label, columns: { x_col, y_col }, temperature_k }]
 *   xKey: string (e.g. 'r', 'time_ps')
 *   zKey: string (e.g. 'g_r', 'msd')
 *   axisLabels: { x, y, z }
 */
export default function CurveSurface3D({
  experiments = [],
  xKey = 'r',
  zKey = 'g_r',
  axisLabels = { x: 'r (\u00C5)', y: 'Temperature (K)', z: 'g(r)' },
}) {
  const [hoveredIdx, setHoveredIdx] = useState(null)

  const { lines, xRange, yRange, zRange } = useMemo(() => {
    if (!experiments.length) return { lines: [], xRange: [0, 1], yRange: [0, 1], zRange: [0, 1] }

    let xMin = Infinity, xMax = -Infinity
    let yMin = Infinity, yMax = -Infinity
    let zMin = Infinity, zMax = -Infinity

    const lineData = experiments
      .filter((exp) => exp.temperature_k != null)
      .map((exp, i) => {
        const xs = exp.columns?.[xKey] || []
        const zs = exp.columns?.[zKey] || []
        const temp = exp.temperature_k

        xs.forEach((v) => { xMin = Math.min(xMin, v); xMax = Math.max(xMax, v) })
        zs.forEach((v) => { zMin = Math.min(zMin, v); zMax = Math.max(zMax, v) })
        yMin = Math.min(yMin, temp)
        yMax = Math.max(yMax, temp)

        return { xs, zs, temp, label: exp.label || exp.expId, index: i }
      })

    if (yMin === yMax) { yMin -= 10; yMax += 10 }
    if (xMin === xMax) { xMax = xMin + 1 }
    if (zMin === zMax) { zMax = zMin + 1 }

    return {
      lines: lineData,
      xRange: [xMin, xMax],
      yRange: [yMin, yMax],
      zRange: [zMin, zMax],
    }
  }, [experiments, xKey, zKey])

  if (!experiments.length) {
    return (
      <div className="text-xs text-slate-500 p-4 text-center">
        Select experiments to view 3D curve visualization
      </div>
    )
  }

  const normalize = (val, min, max) => {
    const range = max - min
    return range > 0 ? ((val - min) / range) * GRID_SIZE * 2 - GRID_SIZE : 0
  }

  return (
    <div className="w-full rounded-lg border overflow-hidden" style={{ height: 400, backgroundColor: ANALYSIS_BG.container, borderColor: ANALYSIS_BG.border }}>
      <Canvas camera={{ position: [14, 10, 14], fov: 50 }}>
        <Suspense fallback={null}>
          <ambientLight intensity={0.75} />
          <pointLight position={[10, 14, 8]} intensity={1.2} />

          {/* Grid */}
          <gridHelper args={[GRID_SIZE * 2, 16, ANALYSIS_BG.grid, ANALYSIS_BG.gridSub]} />

          {/* Axes - using shared AxisLines component */}
          <AxisLines
            size={GRID_SIZE}
            labels={{
              x: axisLabels.x,
              y: axisLabels.z,  // Y axis (vertical) shows z metric value
              z: axisLabels.y,  // Z axis (depth) shows temperature
            }}
          />

          {/* Polylines */}
          {lines.map((line) => {
            const points = []
            const n = Math.min(line.xs.length, line.zs.length)
            for (let j = 0; j < n; j++) {
              const x = normalize(line.xs[j], xRange[0], xRange[1])
              const y = normalize(line.zs[j], zRange[0], zRange[1])
              const z = normalize(line.temp, yRange[0], yRange[1])
              points.push([x, Math.max(y, -GRID_SIZE), z])
            }
            if (points.length < 2) return null

            const color = getChartColorByIndex(line.index)
            const isHovered = hoveredIdx === line.index

            return (
              <group key={line.index}>
                <Line
                  points={points}
                  color={color}
                  lineWidth={isHovered ? 3 : 1.5}
                  onPointerOver={() => setHoveredIdx(line.index)}
                  onPointerOut={() => setHoveredIdx(null)}
                />
                {/* Label at end of line */}
                {points.length > 0 && (
                  <Text
                    position={[
                      points[points.length - 1][0] + 0.4,
                      points[points.length - 1][1] + 0.3,
                      points[points.length - 1][2],
                    ]}
                    fontSize={0.28}
                    color={color}
                    anchorX="left"
                  >
                    {line.label}
                  </Text>
                )}
              </group>
            )
          })}

          <OrbitControls enablePan enableZoom enableRotate minDistance={6} maxDistance={36} />
        </Suspense>
      </Canvas>
    </div>
  )
}

