/**
 * Analysis Tab 4: Composition Transitions
 *
 * Contains: State Graph 2D/3D + GHG by Group comparison.
 */

import { useState, useEffect, useMemo } from 'react'
import { GitBranch, Route, Star, Box, Square, Info } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import { getAnalysisAdditiveColor } from '../../lib/colorPresets'
import StateGraph from './StateGraph2D'
import StateGraph3D from './StateGraph3D'
import GHGByGroupSection from './GHGByGroupSection'

export default function TransitionsTab({ graphData, loading, demoDataEnabled }) {
  const [selectedNode, setSelectedNode] = useState(null)
  const [hoveredNode, setHoveredNode] = useState(null)
  const [showRecommended, setShowRecommended] = useState(false)
  const [viewMode, setViewMode] = useState('2d')

  useEffect(() => { setSelectedNode(null) }, [graphData])

  // Extract additive types from graphData (SSOT: only show what exists in DB)
  const additiveTypesInGraph = useMemo(() => {
    if (!graphData?.nodes) return []
    const types = new Set()
    graphData.nodes.forEach(n => {
      if (n.type && n.type !== 'base') types.add(n.type)
    })
    return [...types].sort()
  }, [graphData])

  return (
    <div className="space-y-6">
      {/* State Graph */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-cyan-400" />
            <h2 className="text-lg font-medium text-white">Composition State Transitions</h2>
            {demoDataEnabled && (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded text-xs">
                <Info className="w-3 h-3" />Synthetic
              </span>
            )}
            {graphData && (
              <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted }}>
                {graphData.nodes.length} states / {graphData.edges.length} transitions
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center rounded-lg p-1" style={{ backgroundColor: ANALYSIS_BG.card }}>
              <button
                onClick={() => setViewMode('2d')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${viewMode === '2d' ? 'bg-cyan-500 text-white' : 'hover:text-white'}`}
                style={viewMode !== '2d' ? { color: ANALYSIS_BG.textMuted } : {}}
              >
                <Square className="w-4 h-4" />2D
              </button>
              <button
                onClick={() => setViewMode('3d')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${viewMode === '3d' ? 'bg-purple-500 text-white' : 'hover:text-white'}`}
                style={viewMode !== '3d' ? { color: ANALYSIS_BG.textMuted } : {}}
              >
                <Box className="w-4 h-4" />3D
              </button>
            </div>

            <button
              onClick={() => setShowRecommended(!showRecommended)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${showRecommended ? 'bg-amber-500 text-slate-900' : 'hover:brightness-125'}`}
              style={showRecommended ? {} : { backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text }}
            >
              <Route className="w-4 h-4" />
              {showRecommended ? 'Hide Path' : 'Show Recommended'}
            </button>
          </div>
        </div>

        <p className="text-sm mb-4" style={{ color: ANALYSIS_BG.textMuted }}>
          Composition states grouped by binder type, aging, and additive. Edges show additive transitions and aging progression.
          {viewMode === '3d' && ' Z-axis represents additive type separation.'}
        </p>

        {graphData ? (
          viewMode === '3d' ? (
            <StateGraph3D data={graphData} selectedNode={selectedNode} hoveredNode={hoveredNode} onSelectNode={setSelectedNode} onHoverNode={setHoveredNode} showRecommended={showRecommended} />
          ) : (
            <StateGraph data={graphData} selectedNode={selectedNode} hoveredNode={hoveredNode} onSelectNode={setSelectedNode} onHoverNode={setHoveredNode} showRecommended={showRecommended} useClustering={graphData.nodes.length > 30} />
          )
        ) : (
          <div className="h-[450px] flex items-center justify-center rounded-lg" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
            <span style={{ color: ANALYSIS_BG.textMuted }}>{loading ? 'Loading graph...' : 'No completed experiment data for state graph.'}</span>
          </div>
        )}

        <div className="flex items-center gap-6 mt-3 text-sm">
          <span style={{ color: ANALYSIS_BG.textMuted }}>Additives:</span>
          {additiveTypesInGraph.length > 0 ? (
            additiveTypesInGraph.map(name => (
              <div key={name} className="flex items-center gap-1">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: getAnalysisAdditiveColor(name) }} />
                <span style={{ color: ANALYSIS_BG.textMuted }}>{name}</span>
              </div>
            ))
          ) : (
            <span style={{ color: ANALYSIS_BG.textMuted, fontStyle: 'italic' }}>No additives in data</span>
          )}
          {showRecommended && (
            <>
              <span className="text-slate-400">|</span>
              <div className="flex items-center gap-1">
                <Star className="w-3 h-3 text-amber-400" fill="#fbbf24" />
                <span className="text-amber-400">Recommended</span>
              </div>
            </>
          )}
        </div>
      </section>

      {/* GHG by Group */}
      <GHGByGroupSection />
    </div>
  )
}
