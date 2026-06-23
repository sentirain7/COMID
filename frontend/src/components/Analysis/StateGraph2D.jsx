import { useState, useRef, useMemo } from 'react'
import { Layers, ChevronDown, ChevronRight, Star, Route } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import { getAnalysisAdditiveColor } from '../../lib/colorPresets'
import useThemeVersion from '../../hooks/useThemeVersion'
import PropertyCard from './PropertyCard'
import { clusterNodes, CLUSTER_THRESHOLD } from './graphUtils'
// Cluster Node component
function ClusterNode({ cluster, isSelected, isExpanded, onToggle, onHover, isHovered }) {
  const color = getAnalysisAdditiveColor(cluster.type)
  const size = 45 + Math.log(cluster.nodes.length + 1) * 15

  return (
    <g
      transform={`translate(${cluster.x}, ${cluster.y})`}
      onClick={(e) => { e.stopPropagation(); onToggle(cluster.id) }}
      onMouseEnter={() => onHover(cluster)}
      onMouseLeave={() => onHover(null)}
      style={{ cursor: 'pointer' }}
    >
      {/* Outer ring for cluster */}
      <circle
        r={size + 5}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeDasharray={isExpanded ? "none" : "8 4"}
        opacity={0.6}
      />

      {/* Selection glow */}
      {isSelected && (
        <circle r={size + 12} fill="none" stroke={color} strokeWidth={3} opacity={0.4} />
      )}

      {/* Main circle */}
      <circle
        r={size}
        fill={`${color}40`}
        stroke={color}
        strokeWidth={isHovered ? 3 : 2}
      />

      {/* Cluster icon */}
      <g transform="translate(-12, -20)">
        <Layers className="w-6 h-6" style={{ color }} />
      </g>

      {/* Label */}
      <text y={5} textAnchor="middle" fill={ANALYSIS_BG.text} fontSize={11} fontWeight={600}>
        {cluster.type}
      </text>

      {/* Node count */}
      <text y={20} textAnchor="middle" fill={ANALYSIS_BG.textMuted} fontSize={10}>
        {cluster.nodes.length} states
      </text>

      {/* Expand indicator */}
      <g transform={`translate(${size - 10}, ${-size + 10})`}>
        <circle r={12} fill={ANALYSIS_BG.card} stroke={color} strokeWidth={1.5} />
        {isExpanded
          ? <ChevronDown className="w-4 h-4" style={{ color: '#e2e8f0', transform: 'translate(-8px, -8px)' }} />
          : <ChevronRight className="w-4 h-4" style={{ color: '#e2e8f0', transform: 'translate(-8px, -8px)' }} />
        }
        <text textAnchor="middle" dominantBaseline="middle" fill={ANALYSIS_BG.text} fontSize={8}>
          {isExpanded ? '−' : '+'}
        </text>
      </g>

      {/* Hover tooltip */}
      {isHovered && (
        <g transform="translate(60, -40)">
          <rect x={0} y={0} width={140} height={90} rx={6} fill={ANALYSIS_BG.card} stroke={ANALYSIS_BG.border} />
          <text x={10} y={18} fill={ANALYSIS_BG.text} fontSize={11} fontWeight={600}>{cluster.label}</text>
          <text x={10} y={34} fill={ANALYSIS_BG.textMuted} fontSize={10}>{cluster.nodes.length} compositions</text>
          <text x={10} y={50} fill={ANALYSIS_BG.textMuted} fontSize={10}>{cluster.experiments} total experiments</text>
          <text x={10} y={66} fill="#10b981" fontSize={10}>
            Avg CED: {cluster.metrics.ced.toFixed(1)} MJ/m³
          </text>
          <text x={10} y={82} fill="#3b82f6" fontSize={10}>
            Avg η: {cluster.metrics.viscosity.toFixed(0)} mPa·s
          </text>
        </g>
      )}
    </g>
  )
}

// Regular Graph Node component
function GraphNode({ node, isSelected, isHovered, isOnRecommendedPath, onSelect, onHover, baseMetrics }) {
  const color = getAnalysisAdditiveColor(node.type)
  const size = 30 + Math.log(node.experiments + 1) * 10

  const deltas = baseMetrics ? {
    density: ((node.metrics.density / baseMetrics.density - 1) * 100).toFixed(1),
    ced: ((node.metrics.ced / baseMetrics.ced - 1) * 100).toFixed(1),
    viscosity: ((node.metrics.viscosity / baseMetrics.viscosity - 1) * 100).toFixed(1),
    adhesion: ((node.metrics.adhesion / baseMetrics.adhesion - 1) * 100).toFixed(1),
  } : null

  return (
    <g
      transform={`translate(${node.x}, ${node.y})`}
      onClick={() => onSelect(node)}
      onMouseEnter={() => onHover(node)}
      onMouseLeave={() => onHover(null)}
      style={{ cursor: 'pointer' }}
    >
      {/* Recommended path glow */}
      {isOnRecommendedPath && (
        <>
          <circle r={size + 15} fill="none" stroke="#fbbf24" strokeWidth={3} opacity={0.3}>
            <animate attributeName="r" values={`${size + 12};${size + 18};${size + 12}`} dur="2s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.3;0.6;0.3" dur="2s" repeatCount="indefinite" />
          </circle>
          <circle r={size + 8} fill="none" stroke="#fbbf24" strokeWidth={2} opacity={0.6} />
        </>
      )}

      {/* Selection glow */}
      {isSelected && !isOnRecommendedPath && (
        <circle r={size + 8} fill="none" stroke={color} strokeWidth={3} opacity={0.5} />
      )}

      {/* Main circle */}
      <circle
        r={size}
        fill={isOnRecommendedPath ? `${color}` : color}
        opacity={isHovered || isSelected || isOnRecommendedPath ? 1 : 0.8}
        stroke={isOnRecommendedPath ? '#fbbf24' : (isHovered ? '#fff' : 'transparent')}
        strokeWidth={isOnRecommendedPath ? 3 : 2}
      />

      {/* Star icon for recommended */}
      {isOnRecommendedPath && (
        <g transform="translate(-6, -6)">
          <Star className="w-3 h-3" fill="#fbbf24" style={{ color: '#fbbf24' }} />
        </g>
      )}

      {/* Label */}
      <text y={size + 16} textAnchor="middle" fill={ANALYSIS_BG.text} fontSize={12} fontWeight={isSelected ? 600 : 400}>
        {node.label}
      </text>

      {/* Experiment count badge */}
      <g transform={`translate(${size - 5}, ${-size + 5})`}>
        <circle r={10} fill={ANALYSIS_BG.card} stroke={color} strokeWidth={1.5} />
        <text textAnchor="middle" dominantBaseline="middle" fill={ANALYSIS_BG.text} fontSize={9} fontWeight={600}>
          {node.experiments}
        </text>
      </g>

      {/* Hover tooltip */}
      {isHovered && node.type !== 'base' && deltas && (
        <g transform="translate(50, -30)">
          <rect x={0} y={0} width={120} height={80} rx={6} fill={ANALYSIS_BG.card} stroke={ANALYSIS_BG.border} />
          <text x={10} y={18} fill={ANALYSIS_BG.textMuted} fontSize={10}>Δ vs Base:</text>
          <text x={10} y={34} fill={deltas.density >= 0 ? '#10b981' : '#ef4444'} fontSize={10}>
            ρ: {deltas.density >= 0 ? '+' : ''}{deltas.density}%
          </text>
          <text x={10} y={48} fill={deltas.ced >= 0 ? '#10b981' : '#ef4444'} fontSize={10}>
            CED: {deltas.ced >= 0 ? '+' : ''}{deltas.ced}%
          </text>
          <text x={10} y={62} fill={deltas.viscosity >= 0 ? '#f59e0b' : '#3b82f6'} fontSize={10}>
            η: {deltas.viscosity >= 0 ? '+' : ''}{deltas.viscosity}%
          </text>
          <text x={10} y={76} fill={deltas.adhesion >= 0 ? '#10b981' : '#ef4444'} fontSize={10}>
            Adh: {deltas.adhesion >= 0 ? '+' : ''}{deltas.adhesion}%
          </text>
        </g>
      )}
    </g>
  )
}

// Graph Edge component
function GraphEdge({ edge, nodes, isHighlighted, isOnRecommendedPath }) {
  const source = nodes.find(n => n.id === edge.source)
  const target = nodes.find(n => n.id === edge.target)
  if (!source || !target) return null

  const dx = target.x - source.x
  const dy = target.y - source.y
  const angle = Math.atan2(dy, dx)

  const sourceRadius = source.nodes ? 45 + Math.log(source.nodes.length + 1) * 15 : 30 + Math.log(source.experiments + 1) * 10
  const targetRadius = target.nodes ? 45 + Math.log(target.nodes.length + 1) * 15 : 30 + Math.log(target.experiments + 1) * 10

  const x1 = source.x + Math.cos(angle) * (sourceRadius + 5)
  const y1 = source.y + Math.sin(angle) * (sourceRadius + 5)
  const x2 = target.x - Math.cos(angle) * (targetRadius + 12)
  const y2 = target.y - Math.sin(angle) * (targetRadius + 12)

  const midX = (x1 + x2) / 2
  const midY = (y1 + y2) / 2

  const color = isOnRecommendedPath ? '#fbbf24' : getAnalysisAdditiveColor(edge.additive)

  return (
    <g opacity={isHighlighted || isOnRecommendedPath ? 1 : 0.5}>
      <defs>
        <marker
          id={`arrow-${edge.source}-${edge.target}`}
          markerWidth={10}
          markerHeight={10}
          refX={8}
          refY={3}
          orient="auto"
          markerUnits="strokeWidth"
        >
          <path d="M0,0 L0,6 L9,3 z" fill={color} />
        </marker>
        {isOnRecommendedPath && (
          <filter id={`glow-${edge.source}-${edge.target}`}>
            <feGaussianBlur stdDeviation="3" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        )}
      </defs>

      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={color}
        strokeWidth={isOnRecommendedPath ? 4 : (isHighlighted ? 3 : 2)}
        markerEnd={`url(#arrow-${edge.source}-${edge.target})`}
        filter={isOnRecommendedPath ? `url(#glow-${edge.source}-${edge.target})` : undefined}
      >
        {isOnRecommendedPath && (
          <animate attributeName="stroke-dasharray" values="0,1000;20,1000" dur="1s" repeatCount="indefinite" />
        )}
      </line>

      <g transform={`translate(${midX}, ${midY})`}>
        <rect
          x={-25} y={-10} width={50} height={20} rx={4}
          fill={isOnRecommendedPath ? '#fbbf24' : '#1e293b'}
          stroke={color}
          strokeWidth={isOnRecommendedPath ? 2 : 1}
        />
        <text
          textAnchor="middle"
          dominantBaseline="middle"
          fill={isOnRecommendedPath ? '#1e293b' : color}
          fontSize={10}
          fontWeight={isOnRecommendedPath ? 600 : 500}
        >
          +{edge.additive}
        </text>
      </g>
    </g>
  )
}

// Main State Graph component
function StateGraph({ data, selectedNode, hoveredNode, onSelectNode, onHoverNode, showRecommended, useClustering }) {
  useThemeVersion('analysis')
  const svgRef = useRef()
  const { nodes, edges, baseMetrics, recommendedPath } = data
  const [expandedClusters, setExpandedClusters] = useState(new Set())

  const shouldCluster = useClustering && nodes.length > CLUSTER_THRESHOLD
  const { clusters, clusterEdges } = useMemo(() =>
    shouldCluster ? clusterNodes(nodes, edges) : { clusters: [], clusterEdges: [] },
    [nodes, edges, shouldCluster]
  )

  const toggleCluster = (clusterId) => {
    setExpandedClusters(prev => {
      const next = new Set(prev)
      if (next.has(clusterId)) next.delete(clusterId)
      else next.add(clusterId)
      return next
    })
  }

  // Get visible nodes based on cluster state
  const visibleNodes = useMemo(() => {
    if (!shouldCluster) return nodes
    const visible = [nodes.find(n => n.type === 'base')]
    clusters.forEach(cluster => {
      if (expandedClusters.has(cluster.id)) {
        visible.push(...cluster.nodes)
      }
    })
    return visible.filter(Boolean)
  }, [nodes, clusters, expandedClusters, shouldCluster])

  // Get visible edges
  const visibleEdges = useMemo(() => {
    if (!shouldCluster) return edges
    const visibleNodeIds = new Set(visibleNodes.map(n => n.id))
    return edges.filter(e => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
  }, [edges, visibleNodes, shouldCluster])

  // Highlighted edges
  const highlightedEdges = useMemo(() => {
    const activeNode = selectedNode || hoveredNode
    if (!activeNode) return []
    return visibleEdges.filter(e => e.source === activeNode.id || e.target === activeNode.id)
  }, [selectedNode, hoveredNode, visibleEdges])

  // Recommended path edges
  const recommendedEdges = useMemo(() => {
    if (!showRecommended || !recommendedPath) return []
    const pathEdges = []
    for (let i = 0; i < recommendedPath.length - 1; i++) {
      const edge = edges.find(e => e.source === recommendedPath[i] && e.target === recommendedPath[i + 1])
      if (edge) pathEdges.push(edge)
    }
    return pathEdges
  }, [showRecommended, recommendedPath, edges])

  const isOnRecommendedPath = (nodeId) => showRecommended && recommendedPath?.includes(nodeId)
  const isEdgeOnRecommendedPath = (edge) => recommendedEdges.includes(edge)

  return (
    <div className="relative h-[450px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
      {/* Clustering indicator */}
      {shouldCluster && (
        <div className="absolute top-4 left-4 z-10 flex items-center gap-2 bg-cyan-500/20 text-cyan-400 px-3 py-2 rounded-lg text-sm">
          <Layers className="w-4 h-4" />
          <span>Auto-clustered ({nodes.length} nodes → {clusters.length} clusters)</span>
        </div>
      )}

      <svg ref={svgRef} width="100%" height="100%" viewBox="0 0 800 450" preserveAspectRatio="xMidYMid meet">
        {/* Cluster edges (when clustered) */}
        {shouldCluster && !expandedClusters.size && (
          <g>
            {clusterEdges.map((edge, idx) => {
              const source = edge.source === 'base'
                ? nodes.find(n => n.type === 'base')
                : clusters.find(c => c.id === edge.source)
              const target = clusters.find(c => c.id === edge.target)
              if (!source || !target) return null
              return (
                <GraphEdge
                  key={`cluster-edge-${idx}`}
                  edge={{ ...edge, source: source.id || 'base', target: target.id }}
                  nodes={[...nodes.filter(n => n.type === 'base'), ...clusters]}
                  isHighlighted={false}
                  isOnRecommendedPath={false}
                />
              )
            })}
          </g>
        )}

        {/* Regular edges */}
        <g>
          {visibleEdges.map((edge) => (
            <GraphEdge
              key={`${edge.source}-${edge.target}`}
              edge={edge}
              nodes={visibleNodes}
              isHighlighted={highlightedEdges.includes(edge)}
              isOnRecommendedPath={isEdgeOnRecommendedPath(edge)}
            />
          ))}
        </g>

        {/* Cluster nodes */}
        {shouldCluster && (
          <g>
            {clusters.filter(c => !expandedClusters.has(c.id)).map(cluster => (
              <ClusterNode
                key={cluster.id}
                cluster={cluster}
                isSelected={selectedNode?.id === cluster.id}
                isExpanded={expandedClusters.has(cluster.id)}
                isHovered={hoveredNode?.id === cluster.id}
                onToggle={toggleCluster}
                onHover={onHoverNode}
              />
            ))}
          </g>
        )}

        {/* Regular nodes */}
        <g>
          {visibleNodes.map(node => (
            <GraphNode
              key={node.id}
              node={node}
              isSelected={selectedNode?.id === node.id}
              isHovered={hoveredNode?.id === node.id}
              isOnRecommendedPath={isOnRecommendedPath(node.id)}
              onSelect={onSelectNode}
              onHover={onHoverNode}
              baseMetrics={baseMetrics}
            />
          ))}
        </g>
      </svg>

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
        {shouldCluster ? 'Click cluster to expand | ' : ''}Click node to select | Hover for details
      </div>
    </div>
  )
}
export default StateGraph
