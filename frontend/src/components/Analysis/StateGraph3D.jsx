import { useRef, useMemo, Suspense } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import { Box, Route } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import { getAnalysisAdditiveColor } from '../../lib/colorPresets'
import useThemeVersion from '../../hooks/useThemeVersion'
import PropertyCard from './PropertyCard'
import { AxisLines } from './ScatterPrimitives'
// 3D Node component
function Node3D({ node, position, isSelected, isHovered, isOnRecommendedPath, onSelect, onHover, baseMetrics, isLargeScale }) {
  const meshRef = useRef()
  const color = getAnalysisAdditiveColor(node.type)
  // Smaller nodes for large scale
  const baseSize = isLargeScale ? 0.15 : 0.3
  const size = baseSize + Math.log(node.experiments + 1) * (isLargeScale ? 0.03 : 0.1)
  const segments = isLargeScale ? 16 : 32 // Lower detail for performance

  useFrame(() => {
    if (meshRef.current) {
      const targetScale = isHovered || isSelected ? 1.5 : 1
      meshRef.current.scale.lerp(new THREE.Vector3(targetScale, targetScale, targetScale), 0.1)
    }
  })

  const deltas = baseMetrics && node.type !== 'base' ? {
    density: ((node.metrics.density / baseMetrics.density - 1) * 100).toFixed(1),
    ced: ((node.metrics.ced / baseMetrics.ced - 1) * 100).toFixed(1),
    viscosity: ((node.metrics.viscosity / baseMetrics.viscosity - 1) * 100).toFixed(1),
  } : null

  // Show labels only for base, selected, hovered, or recommended nodes in large scale
  const showLabel = !isLargeScale || node.type === 'base' || isSelected || isHovered || isOnRecommendedPath

  return (
    <group position={position}>
      {/* Recommended path glow ring */}
      {isOnRecommendedPath && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[size + 0.15, 0.04, 8, 24]} />
          <meshBasicMaterial color="#fbbf24" transparent opacity={0.7} />
        </mesh>
      )}

      {/* Selection ring */}
      {isSelected && !isOnRecommendedPath && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[size + 0.12, 0.03, 8, 24]} />
          <meshBasicMaterial color={color} transparent opacity={0.6} />
        </mesh>
      )}

      {/* Main sphere */}
      <mesh
        ref={meshRef}
        onClick={(e) => { e.stopPropagation(); onSelect(node) }}
        onPointerOver={(e) => { e.stopPropagation(); onHover(node) }}
        onPointerOut={() => onHover(null)}
      >
        <sphereGeometry args={[size, segments, segments]} />
        <meshStandardMaterial
          color={color}
          emissive={isOnRecommendedPath ? '#fbbf24' : (isHovered ? color : '#000000')}
          emissiveIntensity={isOnRecommendedPath ? 0.5 : (isHovered ? 0.4 : 0)}
          roughness={0.4}
          metalness={0.3}
        />
      </mesh>

      {/* Label - only show for important nodes in large scale */}
      {showLabel && (
        <Html
          position={[0, -size - 0.3, 0]}
          center
          style={{ pointerEvents: 'none' }}
        >
          <div className="text-center whitespace-nowrap">
            <div className="text-xs font-medium" style={{ color: isOnRecommendedPath ? '#fbbf24' : ANALYSIS_BG.text }}>
              {isLargeScale ? node.type : node.label}
            </div>
            {!isLargeScale && <div className="text-[10px]" style={{ color: ANALYSIS_BG.textMuted }}>{node.experiments} exp</div>}
          </div>
        </Html>
      )}

      {/* Hover tooltip */}
      {isHovered && deltas && (
        <Html position={[size + 0.5, 0.3, 0]} style={{ pointerEvents: 'none' }}>
          <div className="rounded-lg px-3 py-2 text-xs whitespace-nowrap shadow-lg" style={{ backgroundColor: ANALYSIS_BG.cardAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
            <div className="font-medium mb-1" style={{ color: ANALYSIS_BG.text }}>{node.label}</div>
            <div className="mb-1" style={{ color: ANALYSIS_BG.textMuted }}>Δ vs Base:</div>
            <div className={parseFloat(deltas.density) >= 0 ? 'text-green-400' : 'text-red-400'}>
              ρ: {parseFloat(deltas.density) >= 0 ? '+' : ''}{deltas.density}%
            </div>
            <div className={parseFloat(deltas.ced) >= 0 ? 'text-green-400' : 'text-red-400'}>
              CED: {parseFloat(deltas.ced) >= 0 ? '+' : ''}{deltas.ced}%
            </div>
            <div className={parseFloat(deltas.viscosity) >= 0 ? 'text-amber-400' : 'text-blue-400'}>
              η: {parseFloat(deltas.viscosity) >= 0 ? '+' : ''}{deltas.viscosity}%
            </div>
          </div>
        </Html>
      )}
    </group>
  )
}

// 3D Edge component
function Edge3D({ edge, sourcePos, targetPos, isHighlighted, isOnRecommendedPath, isLargeScale }) {
  const color = isOnRecommendedPath ? '#fbbf24' : getAnalysisAdditiveColor(edge.additive)

  // Calculate midpoint for label
  const midPoint = [
    (sourcePos[0] + targetPos[0]) / 2,
    (sourcePos[1] + targetPos[1]) / 2,
    (sourcePos[2] + targetPos[2]) / 2,
  ]

  // Show labels only for highlighted or recommended edges in large scale
  const showLabel = !isLargeScale || isHighlighted || isOnRecommendedPath

  return (
    <group>
      <Line
        points={[sourcePos, targetPos]}
        color={color}
        lineWidth={isOnRecommendedPath ? 4 : (isHighlighted ? 3 : (isLargeScale ? 1 : 2))}
        transparent
        opacity={isHighlighted || isOnRecommendedPath ? 1 : (isLargeScale ? 0.3 : 0.5)}
      />

      {/* Edge label - hide for large scale unless highlighted */}
      {showLabel && (
        <Html position={midPoint} center style={{ pointerEvents: 'none' }}>
          <div
            className="px-2 py-0.5 rounded text-[10px] font-medium"
            style={isOnRecommendedPath
              ? { backgroundColor: '#f59e0b', color: '#0f172a', borderColor: color, borderWidth: 1 }
              : { backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, borderColor: color, borderWidth: 1 }
            }
          >
            +{edge.additive}
          </div>
        </Html>
      )}
    </group>
  )
}

// 3D Scene for State Graph
function Scene3DGraph({ data, selectedNode, hoveredNode, onSelectNode, onHoverNode, showRecommended }) {
  const { nodes, edges, baseMetrics, recommendedPath } = data
  const isLargeScale = nodes.length > 20

  // Calculate 3D positions with radial layout by additive type
  const nodePositions = useMemo(() => {
    const positions = {}
    if (isLargeScale) {
      // Radial 3D layout: group by additive type in a circular pattern
      const typeGroups = {}
      nodes.forEach(node => {
        if (node.type === 'base') return
        if (!typeGroups[node.type]) typeGroups[node.type] = []
        typeGroups[node.type].push(node)
      })

      // Base node at center
      positions['base'] = [0, 0, 0]

      // Arrange each type group in a radial sector
      const typeKeys = Object.keys(typeGroups)
      typeKeys.forEach((type, typeIdx) => {
        const angle = (typeIdx / typeKeys.length) * Math.PI * 2
        const groupNodes = typeGroups[type]

        groupNodes.forEach((node, nodeIdx) => {
          const radius = 3 + (nodeIdx % 3) * 1.5 // Layered radii
          const heightOffset = Math.floor(nodeIdx / 3) * 1.2 - 1.5 // Vertical stacking
          const angleOffset = (nodeIdx % 3) * 0.15 // Slight angle variation

          const x = Math.cos(angle + angleOffset) * radius
          const z = Math.sin(angle + angleOffset) * radius
          const y = heightOffset

          positions[node.id] = [x, y, z]
        })
      })
    } else {
      // Simple layout for small graphs
      const typeZLevels = { base: 0, SBS: 1, PPA: 2, Sulfur: -1, WMA: -2, SiO2: 1.5, Lignin: -1.5 }

      nodes.forEach(node => {
        const x = (node.x - 400) / 80
        const y = (200 - node.y) / 80
        const z = (typeZLevels[node.type] || 0) * 1.5

        positions[node.id] = [x, y, z]
      })
    }

    return positions
  }, [nodes, isLargeScale])

  const recommendedEdges = useMemo(() => {
    if (!showRecommended || !recommendedPath) return []
    const pathEdges = []
    for (let i = 0; i < recommendedPath.length - 1; i++) {
      const edge = edges.find(e => e.source === recommendedPath[i] && e.target === recommendedPath[i + 1])
      if (edge) pathEdges.push(edge)
    }
    return pathEdges
  }, [showRecommended, recommendedPath, edges])

  const highlightedEdges = useMemo(() => {
    const activeNode = selectedNode || hoveredNode
    if (!activeNode) return []
    return edges.filter(e => e.source === activeNode.id || e.target === activeNode.id)
  }, [selectedNode, hoveredNode, edges])

  const isOnRecommendedPath = (nodeId) => showRecommended && recommendedPath?.includes(nodeId)

  return (
    <>
      <ambientLight intensity={0.6} />
      <pointLight position={[10, 10, 10]} intensity={1} />
      <pointLight position={[-10, -10, 10]} intensity={0.5} />
      <pointLight position={[0, -10, -10]} intensity={0.3} />

      {/* Grid helper - larger for large scale */}
      <gridHelper
        args={[isLargeScale ? 20 : 15, isLargeScale ? 20 : 15, ANALYSIS_BG.grid, ANALYSIS_BG.gridSub]}
        rotation={[0, 0, 0]}
        position={[0, isLargeScale ? -4 : -3, 0]}
      />

      {/* Axis lines */}
      <group position={[0, isLargeScale ? -4 : -3, 0]}>
        <AxisLines
          size={isLargeScale ? 10 : 7.5}
          labels={{
            x: 'Composition',
            y: 'Property',
            z: 'Additive',
          }}
        />
      </group>

      {/* Additive type labels for large scale */}
      {isLargeScale && (
        <>
          {['SBS', 'PPA', 'Sulfur', 'WMA', 'SiO2', 'Lignin'].map((type, idx) => {
            const angle = (idx / 6) * Math.PI * 2
            const radius = 7
            const typeColor = getAnalysisAdditiveColor(type)
            return (
              <Html
                key={type}
                position={[Math.cos(angle) * radius, -3.5, Math.sin(angle) * radius]}
                center
              >
                <div
                  className="px-2 py-1 rounded text-xs font-medium"
                  style={{ backgroundColor: `${typeColor}40`, color: typeColor }}
                >
                  {type}
                </div>
              </Html>
            )
          })}
        </>
      )}

      {/* Edges */}
      {edges.map((edge) => {
        const sourcePos = nodePositions[edge.source]
        const targetPos = nodePositions[edge.target]
        if (!sourcePos || !targetPos) return null

        return (
          <Edge3D
            key={`${edge.source}-${edge.target}`}
            edge={edge}
            sourcePos={sourcePos}
            targetPos={targetPos}
            isHighlighted={highlightedEdges.includes(edge)}
            isOnRecommendedPath={recommendedEdges.includes(edge)}
            isLargeScale={isLargeScale}
          />
        )
      })}

      {/* Nodes */}
      {nodes.map(node => (
        <Node3D
          key={node.id}
          node={node}
          position={nodePositions[node.id]}
          isSelected={selectedNode?.id === node.id}
          isHovered={hoveredNode?.id === node.id}
          isOnRecommendedPath={isOnRecommendedPath(node.id)}
          onSelect={onSelectNode}
          onHover={onHoverNode}
          baseMetrics={baseMetrics}
          isLargeScale={isLargeScale}
        />
      ))}

      <OrbitControls
        enablePan
        enableZoom
        enableRotate
        minDistance={isLargeScale ? 8 : 5}
        maxDistance={isLargeScale ? 40 : 30}
        target={[0, 0, 0]}
      />
    </>
  )
}

// 3D State Graph wrapper component
function StateGraph3D({ data, selectedNode, hoveredNode, onSelectNode, onHoverNode, showRecommended }) {
  useThemeVersion('analysis')
  const { nodes, baseMetrics, recommendedPath } = data
  const isLargeScale = nodes.length > 20

  const isOnRecommendedPath = (nodeId) => showRecommended && recommendedPath?.includes(nodeId)

  // Camera position based on scale
  const cameraPosition = isLargeScale ? [12, 10, 12] : [8, 6, 8]

  return (
    <div className="relative h-[450px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
      <Canvas camera={{ position: cameraPosition, fov: 50 }}>
        <Suspense fallback={null}>
          <Scene3DGraph
            data={data}
            selectedNode={selectedNode}
            hoveredNode={hoveredNode}
            onSelectNode={onSelectNode}
            onHoverNode={onHoverNode}
            showRecommended={showRecommended}
          />
        </Suspense>
      </Canvas>

      {/* Property card */}
      {selectedNode && (
        <div className="absolute top-4 right-4 w-64">
          <PropertyCard
            node={selectedNode}
            baseMetrics={baseMetrics}
            isRecommended={isOnRecommendedPath(selectedNode.id)}
          />
        </div>
      )}

      {/* Recommended path info */}
      {showRecommended && recommendedPath && (
        <div className="absolute bottom-4 right-4 bg-amber-500/20 rounded-lg px-3 py-2 text-xs text-amber-400">
          <div className="flex items-center gap-2 mb-1">
            <Route className="w-4 h-4" />
            <span className="font-medium">Recommended Path</span>
          </div>
          <div className="text-amber-300">
            {recommendedPath.map((id, idx) => (
              <span key={id}>
                {idx > 0 && ' → '}
                {nodes.find(n => n.id === id)?.label || id}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="absolute bottom-4 left-4 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
        Drag to rotate | Scroll to zoom | Click node to select
      </div>

      {/* 3D indicator with node count */}
      <div className="absolute top-4 left-4 flex items-center gap-2 bg-purple-500/20 text-purple-400 px-3 py-2 rounded-lg text-sm">
        <Box className="w-4 h-4" />
        <span>3D View</span>
        <span className="text-purple-300">({nodes.length} nodes)</span>
      </div>
    </div>
  )
}
export default StateGraph3D
