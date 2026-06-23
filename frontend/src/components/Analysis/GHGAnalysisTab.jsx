/**
 * Analysis Tab 3: GHG & Sustainability
 *
 * Contains:
 * - [Top] Bulk Property vs GHG Emission (moved from original section 2)
 * - [Bottom] Layered Property vs GHG (new — cross-analysis)
 */

import { useState, useMemo } from 'react'
import { Leaf, Layers as LayersIcon } from 'lucide-react'
import { Canvas } from '@react-three/fiber'
import { ANALYSIS_BG, SCATTER3D_AXIS_OPTIONS, LAYERED_3D_AXIS_OPTIONS, LAYERED_COLOR_BY_OPTIONS, LAYER_TYPE_LABELS } from '../../lib/constants'
import { useScatter3D, useLayeredAnalysis3D } from '../../hooks/useApi'
import { ScatterScene } from './BinderPropertyViews'
import { ScatterCanvas, ScatterPoint, AxisLines, CategoryTickLabels } from './ScatterPrimitives'
import { getLayeredPointColor, buildScatterData } from './layeredScatterUtils'

export default function GHGAnalysisTab() {
  const [ghgAxisX, setGhgAxisX] = useState('density')
  const [ghgAxisY, setGhgAxisY] = useState('cohesive_energy_density')
  const [hoveredGhgPoint, setHoveredGhgPoint] = useState(null)

  // Layered GHG cross-analysis state
  const [layAxisX, setLayAxisX] = useState('adhesion_energy')
  const [layAxisY, setLayAxisY] = useState('tensile_strength')
  const [layColorBy, setLayColorBy] = useState('layer_type')
  const [hoveredLayPoint, setHoveredLayPoint] = useState(null)

  const { data: ghgData, loading: ghgLoading, error: ghgError } = useScatter3D(ghgAxisX, ghgAxisY, 'ghg_emission', 'bulk_ff_gaff2', 60000)
  const { data: layeredData, loading: layLoading } = useLayeredAnalysis3D({})

  const layItems = useMemo(() => layeredData?.items || [], [layeredData])
  const { points: layPoints, catX: layCatX, catY: layCatY } = useMemo(
    () => buildScatterData(layItems, layAxisX, layAxisY, 'ghg_emission'),
    [layItems, layAxisX, layAxisY]
  )
  const layAxisOptions = LAYERED_3D_AXIS_OPTIONS.filter((o) => o.type === 'continuous' && o.value !== 'ghg_emission')

  // Legend items for layered scatter
  const layLegend = useMemo(() => {
    const seen = new Set()
    layPoints.forEach((p) => { const v = p[layColorBy]; if (v != null) seen.add(String(v)) })
    return [...seen].sort().map((v) => ({
      name: layColorBy === 'layer_type' ? (LAYER_TYPE_LABELS[v] || v) : layColorBy === 'has_water' ? (v === 'true' ? 'Wet' : 'Dry') : v,
      color: getLayeredPointColor({ [layColorBy]: layColorBy === 'has_water' ? v === 'true' : v }, layColorBy),
    }))
  }, [layPoints, layColorBy])

  return (
    <div className="space-y-6">
      {/* Bulk Property vs GHG */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Leaf className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-medium text-white">Bulk Property vs GHG Emission</h2>
        </div>

        <div className="flex items-center gap-3 mb-4">
          <label className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>X:</label>
          <select value={ghgAxisX} onChange={(e) => setGhgAxisX(e.target.value)} className="text-sm rounded-lg px-3 py-2" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            {SCATTER3D_AXIS_OPTIONS.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
          </select>
          <label className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>Y:</label>
          <select value={ghgAxisY} onChange={(e) => setGhgAxisY(e.target.value)} className="text-sm rounded-lg px-3 py-2" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            {SCATTER3D_AXIS_OPTIONS.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
          </select>
          <span className="text-sm px-3 py-2 rounded-lg" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            Z: GHG Emission (kg CO&#x2082;-eq/kg)
          </span>
        </div>

        <div className="relative">
          {Array.isArray(ghgData) && ghgData.length > 0 ? (
            <div className="relative h-[420px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
              <div className="absolute top-3 left-3 z-10 text-xs px-2 py-1 rounded" style={{ color: ANALYSIS_BG.text, backgroundColor: ANALYSIS_BG.overlay }}>
                Property vs GHG Trade-off ({ghgData.length} experiments)
              </div>
              <Canvas camera={{ position: [11, 10, 11], fov: 50 }}>
                <ScatterScene
                  points={ghgData}
                  hovered={hoveredGhgPoint}
                  onHover={setHoveredGhgPoint}
                  axisLabels={{
                    x: SCATTER3D_AXIS_OPTIONS.find((o) => o.value === ghgAxisX)?.label || ghgAxisX,
                    y: SCATTER3D_AXIS_OPTIONS.find((o) => o.value === ghgAxisY)?.label || ghgAxisY,
                    z: 'GHG (kg CO\u2082-eq/kg)',
                  }}
                />
              </Canvas>
            </div>
          ) : ghgError ? (
            <div className="h-[420px] flex items-center justify-center rounded-lg text-red-300" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
              Failed to load GHG scatter data.
            </div>
          ) : ghgLoading ? (
            <div className="h-[420px] flex items-center justify-center rounded-lg" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}`, color: ANALYSIS_BG.textMuted }}>
              Loading GHG visualization...
            </div>
          ) : (
            <div className="h-[420px] flex items-center justify-center rounded-lg" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}`, color: ANALYSIS_BG.textMuted }}>
              No completed experiment data with GHG info yet.
            </div>
          )}
        </div>

        <div className="mt-3 min-h-[32px]">
          {hoveredGhgPoint ? (
            <div className="flex flex-nowrap gap-2 text-xs overflow-x-auto" style={{ color: ANALYSIS_BG.text }}>
              {[
                hoveredGhgPoint.exp_id,
                `Binder: ${hoveredGhgPoint.binder_type || '-'}`,
                `Additive: ${hoveredGhgPoint.additive || 'none'}`,
                `${SCATTER3D_AXIS_OPTIONS.find((o) => o.value === ghgAxisX)?.label || ghgAxisX}: ${Number(hoveredGhgPoint.axis_x_value || 0).toFixed(4)}`,
                `${SCATTER3D_AXIS_OPTIONS.find((o) => o.value === ghgAxisY)?.label || ghgAxisY}: ${Number(hoveredGhgPoint.axis_y_value || 0).toFixed(4)}`,
                `GHG: ${Number(hoveredGhgPoint.axis_z_value || 0).toFixed(3)} kg CO\u2082-eq/kg`,
              ].map((label) => (
                <span key={label} className="px-2 py-1 rounded whitespace-nowrap" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>{label}</span>
              ))}
            </div>
          ) : (
            <div className="text-xs py-1" style={{ color: ANALYSIS_BG.textMuted, opacity: 0.4 }}>Hover over a point to see details</div>
          )}
        </div>
      </section>

      {/* Layered Property vs GHG (new cross-analysis) */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <LayersIcon className="w-5 h-5 text-teal-400" />
          <h2 className="text-lg font-medium text-white">Layered Structure vs GHG</h2>
        </div>

        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <label className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>X:</label>
          <select value={layAxisX} onChange={(e) => setLayAxisX(e.target.value)} className="text-sm rounded-lg px-3 py-2" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            {layAxisOptions.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
          </select>
          <label className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>Y:</label>
          <select value={layAxisY} onChange={(e) => setLayAxisY(e.target.value)} className="text-sm rounded-lg px-3 py-2" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            {layAxisOptions.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
          </select>
          <span className="text-sm px-3 py-2 rounded-lg" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            Z: GHG (kgCO&#x2082;e/kg)
          </span>
          <label className="text-sm ml-2" style={{ color: ANALYSIS_BG.textMuted }}>Color:</label>
          <select value={layColorBy} onChange={(e) => setLayColorBy(e.target.value)} className="text-sm rounded-lg px-3 py-2" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            {LAYERED_COLOR_BY_OPTIONS.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
          </select>
        </div>

        <div className="relative h-[420px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
          {layPoints.length > 0 ? (
            <>
              <div className="absolute top-3 left-3 z-10 text-xs px-2 py-1 rounded" style={{ color: ANALYSIS_BG.text, backgroundColor: ANALYSIS_BG.overlay }}>
                Layered vs GHG ({layPoints.length} experiments)
              </div>
              <Canvas camera={{ position: [11, 10, 11], fov: 50 }}>
                <ScatterCanvas>
                  {layPoints.map((item) => (
                    <ScatterPoint
                      key={item.exp_id}
                      item={item}
                      isHovered={hoveredLayPoint?.exp_id === item.exp_id}
                      onHover={setHoveredLayPoint}
                      color={getLayeredPointColor(item, layColorBy)}
                    />
                  ))}
                  <AxisLines labels={{
                    x: LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === layAxisX)?.label || layAxisX,
                    y: LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === layAxisY)?.label || layAxisY,
                    z: 'GHG (kgCO\u2082e/kg)',
                  }} />
                  {layCatX && <CategoryTickLabels categories={layCatX} axis="x" />}
                  {layCatY && <CategoryTickLabels categories={layCatY} axis="y" />}
                </ScatterCanvas>
              </Canvas>
            </>
          ) : layLoading ? (
            <div className="h-full flex items-center justify-center" style={{ color: ANALYSIS_BG.textMuted }}>Loading layered GHG data...</div>
          ) : (
            <div className="h-full flex items-center justify-center" style={{ color: ANALYSIS_BG.textMuted }}>No layered experiments with GHG data.</div>
          )}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 mt-3 flex-wrap">
          {layLegend.map((item) => (
            <div key={item.name} className="flex items-center gap-1.5 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
              {item.name}
            </div>
          ))}
        </div>

        <div className="mt-2 min-h-[32px]">
          {hoveredLayPoint ? (
            <div className="flex flex-nowrap gap-2 text-xs overflow-x-auto" style={{ color: ANALYSIS_BG.text }}>
              {[
                hoveredLayPoint.exp_id,
                `Layer: ${LAYER_TYPE_LABELS[hoveredLayPoint.layer_type] || hoveredLayPoint.layer_type || '-'}`,
                `Crystal: ${hoveredLayPoint.crystal_material || '-'}`,
                `Binder: ${hoveredLayPoint.binder_type || '-'}${hoveredLayPoint.binder_type_secondary ? ' / ' + hoveredLayPoint.binder_type_secondary : ''}`,
                `Aging: ${hoveredLayPoint.aging_state || '-'}${hoveredLayPoint.aging_state_secondary ? ' / ' + hoveredLayPoint.aging_state_secondary : ''}`,
                `${LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === layAxisX)?.label || layAxisX}: ${Number(hoveredLayPoint[layAxisX] || 0).toFixed(3)}`,
                `${LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === layAxisY)?.label || layAxisY}: ${Number(hoveredLayPoint[layAxisY] || 0).toFixed(3)}`,
                `GHG: ${Number(hoveredLayPoint.ghg_emission || 0).toFixed(3)}`,
              ].map((label) => (
                <span key={label} className="px-2 py-1 rounded whitespace-nowrap" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>{label}</span>
              ))}
            </div>
          ) : (
            <div className="text-xs py-1" style={{ color: ANALYSIS_BG.textMuted, opacity: 0.4 }}>Hover over a point to see details</div>
          )}
        </div>
      </section>
    </div>
  )
}
