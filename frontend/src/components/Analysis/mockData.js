const generateMockEmbeddingData = () => {
  const categories = ['saturate', 'aromatic', 'resin', 'asphaltene', 'additive']
  const molecules = []

  categories.forEach((category, catIndex) => {
    const centerX = (catIndex - 2) * 3
    const centerY = Math.sin(catIndex) * 2
    const centerZ = Math.cos(catIndex) * 2
    const count = category === 'additive' ? 3 : 5 + Math.floor(Math.random() * 3)

    for (let i = 0; i < count; i++) {
      molecules.push({
        mol_id: `${category.toUpperCase().slice(0, 3)}_${String(i + 1).padStart(3, '0')}`,
        mol_name: `${category.charAt(0).toUpperCase() + category.slice(1)} ${i + 1}`,
        category,
        position: [
          centerX + (Math.random() - 0.5) * 2,
          centerY + (Math.random() - 0.5) * 2,
          centerZ + (Math.random() - 0.5) * 2,
        ],
        metrics: {
          density_impact: (Math.random() - 0.5) * 0.1,
          ced_impact: (Math.random() - 0.5) * 50,
          viscosity_impact: (Math.random() - 0.5) * 100,
        },
        experiment_count: Math.floor(Math.random() * 20) + 1,
      })
    }
  })

  return molecules
}

const generateMockGraphData = (nodeCount = 6) => {
  const baseMetrics = { density: 1.02, ced: 320, viscosity: 450, adhesion: 85 }
  const additiveTypes = ['SBS', 'PPA', 'Sulfur', 'WMA', 'SiO2', 'Lignin']

  const nodes = []
  const edges = []

  // Base node
  nodes.push({
    id: 'base',
    label: 'Base Binder',
    type: 'base',
    metrics: { ...baseMetrics },
    x: 400, y: 200,
    experiments: 12,
    cluster: null,
  })

  if (nodeCount <= 20) {
    // Simple graph (original behavior)
    const simpleNodes = [
      { id: 'base+sbs', label: 'Base + SBS', type: 'SBS', mult: { d: 0.98, c: 1.12, v: 1.28, a: 1.15 }, x: 200, y: 100, exp: 8 },
      { id: 'base+ppa', label: 'Base + PPA', type: 'PPA', mult: { d: 1.01, c: 1.08, v: 1.45, a: 1.05 }, x: 600, y: 100, exp: 6 },
      { id: 'base+sulfur', label: 'Base + Sulfur', type: 'Sulfur', mult: { d: 1.02, c: 1.05, v: 1.15, a: 0.95 }, x: 200, y: 300, exp: 5 },
      { id: 'base+wma', label: 'Base + WMA', type: 'WMA', mult: { d: 0.99, c: 0.95, v: 0.75, a: 1.02 }, x: 600, y: 300, exp: 4 },
      { id: 'base+sbs+ppa', label: 'Base + SBS + PPA', type: 'SBS', mult: { d: 0.97, c: 1.18, v: 1.65, a: 1.22 }, x: 400, y: 50, exp: 3 },
    ]

    simpleNodes.forEach(n => {
      nodes.push({
        id: n.id, label: n.label, type: n.type,
        metrics: {
          density: baseMetrics.density * n.mult.d,
          ced: baseMetrics.ced * n.mult.c,
          viscosity: baseMetrics.viscosity * n.mult.v,
          adhesion: baseMetrics.adhesion * n.mult.a,
        },
        x: n.x, y: n.y, experiments: n.exp, cluster: null,
      })
    })

    edges.push(
      { source: 'base', target: 'base+sbs', additive: 'SBS', wt: 3 },
      { source: 'base', target: 'base+ppa', additive: 'PPA', wt: 2 },
      { source: 'base', target: 'base+sulfur', additive: 'Sulfur', wt: 5 },
      { source: 'base', target: 'base+wma', additive: 'WMA', wt: 1 },
      { source: 'base+sbs', target: 'base+sbs+ppa', additive: 'PPA', wt: 2 },
      { source: 'base+ppa', target: 'base+sbs+ppa', additive: 'SBS', wt: 3 },
    )
  } else {
    // Large graph - generate many nodes for clustering demo
    const gridCols = Math.ceil(Math.sqrt(nodeCount))
    const spacing = 700 / gridCols

    for (let i = 0; i < nodeCount - 1; i++) {
      const additive = additiveTypes[i % additiveTypes.length]
      const variant = Math.floor(i / additiveTypes.length) + 1
      const row = Math.floor(i / gridCols)
      const col = i % gridCols

      nodes.push({
        id: `node_${i}`,
        label: `${additive} v${variant}`,
        type: additive,
        metrics: {
          density: baseMetrics.density * (0.95 + Math.random() * 0.1),
          ced: baseMetrics.ced * (0.9 + Math.random() * 0.3),
          viscosity: baseMetrics.viscosity * (0.7 + Math.random() * 0.8),
          adhesion: baseMetrics.adhesion * (0.85 + Math.random() * 0.3),
        },
        x: 80 + col * spacing,
        y: 50 + row * spacing * 0.6,
        experiments: Math.floor(Math.random() * 15) + 1,
        cluster: additive, // Pre-assign cluster
      })

      // Create edges from base to first level
      if (variant === 1) {
        edges.push({ source: 'base', target: `node_${i}`, additive, wt: Math.floor(Math.random() * 5) + 1 })
      } else if (i >= additiveTypes.length) {
        // Connect to previous variant of same additive
        const prevIdx = i - additiveTypes.length
        edges.push({ source: `node_${prevIdx}`, target: `node_${i}`, additive, wt: Math.floor(Math.random() * 3) + 1 })
      }
    }
  }

  // Recommended path (mock)
  const recommendedPath = nodeCount <= 20
    ? ['base', 'base+sbs', 'base+sbs+ppa']
    : ['base', 'node_0', 'node_6', 'node_12']

  return { nodes, edges, baseMetrics, recommendedPath }
}
export { generateMockEmbeddingData, generateMockGraphData }
