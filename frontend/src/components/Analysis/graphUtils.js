const CLUSTER_THRESHOLD = 30 // Auto-cluster when nodes exceed this

// Cluster nodes by additive type
function clusterNodes(nodes, edges) {
  const clusters = {}

  // Group nodes by type (excluding base)
  nodes.forEach(node => {
    if (node.type === 'base') return
    const clusterKey = node.type
    if (!clusters[clusterKey]) {
      clusters[clusterKey] = {
        id: `cluster_${clusterKey}`,
        type: clusterKey,
        label: `${clusterKey} Cluster`,
        nodes: [],
        expanded: false,
      }
    }
    clusters[clusterKey].nodes.push(node)
  })

  // Calculate cluster positions and aggregate metrics
  Object.values(clusters).forEach((cluster) => {
    const avgX = cluster.nodes.reduce((sum, n) => sum + n.x, 0) / cluster.nodes.length
    const avgY = cluster.nodes.reduce((sum, n) => sum + n.y, 0) / cluster.nodes.length
    cluster.x = avgX
    cluster.y = avgY
    cluster.experiments = cluster.nodes.reduce((sum, n) => sum + n.experiments, 0)
    cluster.metrics = {
      density: cluster.nodes.reduce((sum, n) => sum + n.metrics.density, 0) / cluster.nodes.length,
      ced: cluster.nodes.reduce((sum, n) => sum + n.metrics.ced, 0) / cluster.nodes.length,
      viscosity: cluster.nodes.reduce((sum, n) => sum + n.metrics.viscosity, 0) / cluster.nodes.length,
      adhesion: cluster.nodes.reduce((sum, n) => sum + n.metrics.adhesion, 0) / cluster.nodes.length,
    }
  })

  // Create cluster edges (aggregate edges between clusters)
  const clusterEdges = []
  const edgeCounts = {}

  edges.forEach(edge => {
    const sourceNode = nodes.find(n => n.id === edge.source)
    const targetNode = nodes.find(n => n.id === edge.target)
    if (!sourceNode || !targetNode) return

    const sourceCluster = sourceNode.type === 'base' ? 'base' : `cluster_${sourceNode.type}`
    const targetCluster = targetNode.type === 'base' ? 'base' : `cluster_${targetNode.type}`

    if (sourceCluster === targetCluster) return

    const edgeKey = `${sourceCluster}->${targetCluster}`
    if (!edgeCounts[edgeKey]) {
      edgeCounts[edgeKey] = { source: sourceCluster, target: targetCluster, count: 0, additive: edge.additive }
    }
    edgeCounts[edgeKey].count++
  })

  Object.values(edgeCounts).forEach(e => {
    clusterEdges.push({ source: e.source, target: e.target, additive: e.additive, count: e.count })
  })

  return { clusters: Object.values(clusters), clusterEdges }
}
// ─── Binder cell naming SSOT ─────────────────────────────────────────────────

import { BINDER_ABBREV, AGING_ABBREV } from '../../lib/constants'
import { canonicalSort } from '../../lib/canonicalOrdering'

/**
 * Short label for graph display.
 * e.g., "A1-NA" for base, "A1-SA+SBS(5%)" for additive state.
 */
function shortenBinderLabel(binderType, agingState, additive, additiveWt) {
  const b = BINDER_ABBREV[binderType] || (binderType ? binderType.slice(0, 2) : '??')
  const a = AGING_ABBREV[agingState] || 'NA'
  if (!additive || additive === 'none') return `${b}-${a}`
  const wt = additiveWt ? `(${additiveWt}%)` : ''
  return `${b}-${a}+${additive}${wt}`
}

/**
 * Build composition state transition graph from embedding property points.
 * Groups experiments by (binder_type, aging_state, additive) into nodes.
 * Creates edges for additive transitions and aging transitions.
 *
 * @param {Array} points - Property points with binder_type, aging_state, additive, density, ced, etc.
 * @returns {{ nodes, edges, baseMetrics, recommendedPath }} or null
 */
function buildGraphFromPoints(points) {
  if (!Array.isArray(points) || points.length === 0) return null

  // Group by state key: binder_type|aging_state|additive
  const groups = new Map()
  points.forEach(p => {
    const binder = p.binder_type || 'unknown'
    const aging = p.aging_state || 'non_aging'
    const additive = p.additive || 'none'
    const key = `${binder}|${aging}|${additive}`
    if (!groups.has(key)) {
      groups.set(key, { binder, aging, additive, points: [], additive_wts: [] })
    }
    const g = groups.get(key)
    g.points.push(p)
    if (p.additive_wt != null && Number(p.additive_wt) > 0) {
      g.additive_wts.push(Number(p.additive_wt))
    }
  })

  // Build nodes
  const nodes = []
  const nodeByKey = new Map()

  groups.forEach((g, key) => {
    const avg = (field) => {
      const vals = g.points.map(p => Number(p[field])).filter(Number.isFinite)
      return vals.length > 0 ? vals.reduce((s, v) => s + v, 0) / vals.length : 0
    }
    const avgWt = g.additive_wts.length > 0
      ? Math.round(g.additive_wts.reduce((s, v) => s + v, 0) / g.additive_wts.length)
      : 0

    const isBase = g.additive === 'none'
    const id = key.replace(/\|/g, '_')
    const label = shortenBinderLabel(g.binder, g.aging, g.additive, avgWt)

    const node = {
      id,
      label,
      type: isBase ? 'base' : g.additive,
      metrics: {
        density: avg('density'),
        ced: avg('ced'),
        viscosity: avg('viscosity') || 0,
        adhesion: avg('adhesion_energy') || 0,
      },
      x: 0,
      y: 0,
      experiments: g.points.length,
      cluster: isBase ? null : g.additive,
      _binder: g.binder,
      _aging: g.aging,
      _additive: g.additive,
    }
    nodes.push(node)
    nodeByKey.set(key, node)
  })

  // Build edges
  const edges = []
  const agingOrder = canonicalSort('aging_state', ['non_aging', 'short_aging', 'long_aging'])

  // 1) Additive transition: base(binder, aging, none) → (binder, aging, additive)
  nodeByKey.forEach((node) => {
    if (node._additive === 'none') return
    const baseKey = `${node._binder}|${node._aging}|none`
    const base = nodeByKey.get(baseKey)
    if (base) {
      edges.push({ source: base.id, target: node.id, additive: node._additive, wt: 0 })
    }
  })

  // 2) Aging transitions: (binder, aging_i, additive) → (binder, aging_i+1, additive)
  const binderAdditives = new Set()
  nodeByKey.forEach(node => binderAdditives.add(`${node._binder}|${node._additive}`))

  binderAdditives.forEach(ba => {
    const [binder, additive] = ba.split('|')
    for (let i = 0; i < agingOrder.length - 1; i++) {
      const from = nodeByKey.get(`${binder}|${agingOrder[i]}|${additive}`)
      const to = nodeByKey.get(`${binder}|${agingOrder[i + 1]}|${additive}`)
      if (from && to) {
        edges.push({
          source: from.id,
          target: to.id,
          additive: `→${AGING_ABBREV[agingOrder[i + 1]] || agingOrder[i + 1]}`,
          wt: 0,
        })
      }
    }
  })

  // Layout: position nodes for 2D rendering
  const binders = canonicalSort('binder_type', [...new Set(nodes.map(n => n._binder))])
  const agings = canonicalSort('aging_state', [...new Set(nodes.map(n => n._aging))])
  const additiveNames = canonicalSort('additive', [...new Set(nodes.filter(n => n._additive !== 'none').map(n => n._additive))])

  nodes.forEach(node => {
    const bi = binders.indexOf(node._binder)
    const ai = agings.indexOf(node._aging)

    if (node._additive === 'none') {
      // Base nodes in a grid
      node.x = 300 + bi * 250
      node.y = 150 + ai * 150
    } else {
      // Additive nodes radiate from their base
      const baseKey = `${node._binder}|${node._aging}|none`
      const base = nodeByKey.get(baseKey)
      const addIdx = additiveNames.indexOf(node._additive)
      const angle = ((addIdx + 0.5) / Math.max(additiveNames.length, 1)) * Math.PI * 1.6 - Math.PI * 0.3
      const radius = 160
      node.x = (base?.x || 400) + Math.cos(angle) * radius
      node.y = (base?.y || 200) + Math.sin(angle) * radius * 0.7
    }
  })

  // Base metrics (average of all base nodes)
  const baseNodes = nodes.filter(n => n._additive === 'none')
  const baseMetrics = baseNodes.length > 0 ? {
    density: baseNodes.reduce((s, n) => s + n.metrics.density, 0) / baseNodes.length,
    ced: baseNodes.reduce((s, n) => s + n.metrics.ced, 0) / baseNodes.length,
    viscosity: baseNodes.reduce((s, n) => s + n.metrics.viscosity, 0) / baseNodes.length,
    adhesion: baseNodes.reduce((s, n) => s + n.metrics.adhesion, 0) / baseNodes.length,
  } : { density: 1.0, ced: 300, viscosity: 400, adhesion: 80 }

  // Recommended path: base → additive node with best combined CED + adhesion improvement
  let bestNode = null
  let bestScore = -Infinity
  nodes.forEach(n => {
    if (n._additive === 'none') return
    const cedImp = baseMetrics.ced > 0 ? (n.metrics.ced / baseMetrics.ced - 1) : 0
    const adhImp = baseMetrics.adhesion > 0 ? (n.metrics.adhesion / baseMetrics.adhesion - 1) : 0
    const score = cedImp + adhImp
    if (score > bestScore) {
      bestScore = score
      bestNode = n
    }
  })

  const recommendedPath = []
  if (bestNode) {
    const baseKey = `${bestNode._binder}|${bestNode._aging}|none`
    const base = nodeByKey.get(baseKey)
    if (base) recommendedPath.push(base.id)
    recommendedPath.push(bestNode.id)
  }

  return { nodes, edges, baseMetrics, recommendedPath }
}

export { CLUSTER_THRESHOLD, clusterNodes, shortenBinderLabel, buildGraphFromPoints }
