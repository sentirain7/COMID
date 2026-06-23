/**
 * Analysis Tab 2: Layered Structures
 *
 * Two 3D scatter charts for multi-variable layered structure analysis:
 * - Chart 1 (left): Adhesion / Energy — default X=temp, Y=crystal, Z=adhesion, color=layer_type
 * - Chart 2 (right): Mechanical Properties — default X=temp, Y=crystal, Z=tensile, color=aging
 */

import { useState, useMemo, useCallback } from 'react'
import { Layers as LayersIcon, Filter, Download } from 'lucide-react'
import { Canvas } from '@react-three/fiber'
import { ANALYSIS_BG, LAYERED_3D_AXIS_OPTIONS, LAYERED_COLOR_BY_OPTIONS, LAYER_TYPE_LABELS } from '../../lib/constants'
import { exportChartToCSV } from '../../lib/csvExport'
import { useLayeredAnalysis3D } from '../../hooks/useApi'
import { ScatterCanvas, ScatterPoint, AxisLines, CategoryTickLabels } from './ScatterPrimitives'
import { getLayeredPointColor, buildScatterData } from './layeredScatterUtils'

function AxisSelect({ value, onChange, label }) {
  return (
    <>
      <label className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>{label}:</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="text-sm rounded-lg px-3 py-1.5" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
        {LAYERED_3D_AXIS_OPTIONS.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
      </select>
    </>
  )
}

function ColorBySelect({ value, onChange }) {
  return (
    <>
      <label className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>Color:</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="text-sm rounded-lg px-3 py-1.5" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
        {LAYERED_COLOR_BY_OPTIONS.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
      </select>
    </>
  )
}

function ScatterLegend({ points, colorBy }) {
  const legend = useMemo(() => {
    const seen = new Set()
    points.forEach((p) => { const v = p[colorBy]; if (v != null) seen.add(String(v)) })
    return [...seen].sort().map((v) => ({
      name: colorBy === 'layer_type' ? (LAYER_TYPE_LABELS[v] || v) : colorBy === 'has_water' ? (v === 'true' ? 'Wet' : 'Dry') : v,
      color: getLayeredPointColor({ [colorBy]: colorBy === 'has_water' ? v === 'true' : v }, colorBy),
    }))
  }, [points, colorBy])

  return (
    <div className="flex items-center gap-3 mt-2 flex-wrap">
      {legend.map((item) => (
        <span key={item.name} className="inline-flex items-center gap-1 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
          {item.name}
        </span>
      ))}
    </div>
  )
}

function ScatterChart({ items, defaultAxisX, defaultAxisY, defaultAxisZ, defaultColorBy, title, hovered, onHover }) {
  const [axisX, setAxisX] = useState(defaultAxisX)
  const [axisY, setAxisY] = useState(defaultAxisY)
  const [axisZ, setAxisZ] = useState(defaultAxisZ)
  const [colorBy, setColorBy] = useState(defaultColorBy)

  const { points, catX, catY, catZ } = useMemo(
    () => buildScatterData(items, axisX, axisY, axisZ),
    [items, axisX, axisY, axisZ]
  )

  const axisLabels = {
    x: LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === axisX)?.label || axisX,
    y: LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === axisY)?.label || axisY,
    z: LAYERED_3D_AXIS_OPTIONS.find((o) => o.value === axisZ)?.label || axisZ,
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <AxisSelect value={axisX} onChange={setAxisX} label="X" />
        <AxisSelect value={axisY} onChange={setAxisY} label="Y" />
        <AxisSelect value={axisZ} onChange={setAxisZ} label="Z" />
        <span className="mx-1" style={{ color: ANALYSIS_BG.border }}>|</span>
        <ColorBySelect value={colorBy} onChange={setColorBy} />
      </div>
      <div className="relative h-[420px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
        {points.length > 0 ? (
          <>
            <div className="absolute top-3 left-3 z-10 text-xs px-2 py-1 rounded" style={{ color: ANALYSIS_BG.text, backgroundColor: ANALYSIS_BG.overlay }}>
              {title} ({points.length} pts)
            </div>
            <Canvas camera={{ position: [11, 10, 11], fov: 50 }}>
              <ScatterCanvas>
                {points.map((item) => (
                  <ScatterPoint
                    key={item.exp_id}
                    item={item}
                    isHovered={hovered?.exp_id === item.exp_id}
                    onHover={onHover}
                    color={getLayeredPointColor(item, colorBy)}
                  />
                ))}
                <AxisLines labels={axisLabels} />
                {catX && <CategoryTickLabels categories={catX} axis="x" />}
                {catY && <CategoryTickLabels categories={catY} axis="y" />}
                {catZ && <CategoryTickLabels categories={catZ} axis="z" />}
              </ScatterCanvas>
            </Canvas>
          </>
        ) : (
          <div className="h-full flex items-center justify-center" style={{ color: ANALYSIS_BG.textMuted }}>
            No data for selected axes.
          </div>
        )}
      </div>
      <ScatterLegend points={points} colorBy={colorBy} />
    </div>
  )
}

export default function LayeredAnalysisTab() {
  const [filters, setFilters] = useState({})
  const [showFilters, setShowFilters] = useState(false)
  const [tempMinDraft, setTempMinDraft] = useState('')
  const [tempMaxDraft, setTempMaxDraft] = useState('')
  const { data, loading } = useLayeredAnalysis3D(filters)

  const applyTempFilter = useCallback(() => {
    setFilters(prev => {
      const updated = { ...prev }
      if (tempMinDraft) updated.temp_min = Number(tempMinDraft); else delete updated.temp_min
      if (tempMaxDraft) updated.temp_max = Number(tempMaxDraft); else delete updated.temp_max
      return updated
    })
  }, [tempMinDraft, tempMaxDraft])

  const resetTempFilter = useCallback(() => {
    setTempMinDraft('')
    setTempMaxDraft('')
    setFilters(prev => {
      const updated = { ...prev }
      delete updated.temp_min
      delete updated.temp_max
      return updated
    })
  }, [])

  const items = data?.items || []
  const availLayerTypes = data?.available_layer_types || []
  const availCrystals = data?.available_crystal_materials || []
  const availAging = data?.available_aging_states || []

  const [hovered1, setHovered1] = useState(null)
  const [hovered2, setHovered2] = useState(null)

  const toggleFilter = (key, value) => {
    setFilters((prev) => {
      const arr = prev[key] || []
      const next = arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value]
      const updated = { ...prev }
      if (next.length) updated[key] = next; else delete updated[key]
      return updated
    })
  }

  const handleExportCSV = () => {
    if (!items.length) return
    const exportData = items.map(item => ({
      exp_id: item.exp_id || '',
      layer_type: item.layer_type || '',
      crystal_material: item.crystal_material || '',
      binder_type: item.binder_type || '',
      binder_type_secondary: item.binder_type_secondary || '',
      aging_state: item.aging_state || '',
      aging_state_secondary: item.aging_state_secondary || '',
      has_water: item.has_water ? 'true' : 'false',
      temperature_K: item.temperature_K || '',
      adhesion_energy: item.adhesion_energy || '',
      tensile_strength: item.tensile_strength || '',
      elastic_modulus: item.elastic_modulus || '',
      toughness: item.toughness || '',
      work_of_separation: item.work_of_separation || '',
      orientation_order: item.orientation_order || '',
      ghg_emission: item.ghg_emission || '',
    }))
    exportChartToCSV(
      exportData,
      ['exp_id', 'layer_type', 'crystal_material', 'binder_type', 'binder_type_secondary', 'aging_state', 'aging_state_secondary', 'has_water', 'temperature_K', 'adhesion_energy', 'tensile_strength', 'elastic_modulus', 'toughness', 'work_of_separation', 'orientation_order', 'ghg_emission'],
      'layered_analysis_data',
      {
        exp_id: 'Experiment ID',
        layer_type: 'Layer Type',
        crystal_material: 'Crystal Material',
        binder_type: 'Binder Type',
        binder_type_secondary: 'Secondary Binder',
        aging_state: 'Aging State',
        aging_state_secondary: 'Secondary Aging',
        has_water: 'Has Water',
        temperature_K: 'Temperature (K)',
        adhesion_energy: 'Adhesion Energy (mJ/m2)',
        tensile_strength: 'Tensile Strength (MPa)',
        elastic_modulus: 'Elastic Modulus (GPa)',
        toughness: 'Toughness (MJ/m3)',
        work_of_separation: 'Work of Separation (mJ/m2)',
        orientation_order: 'Orientation Order',
        ghg_emission: 'GHG Emission (kg CO2-eq/kg)',
      }
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <LayersIcon className="w-5 h-5 text-violet-400" />
          <h2 className="text-lg font-medium text-white">Layered Structure 3D Analysis</h2>
          {loading && <span className="text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-300">Loading...</span>}
          {items.length > 0 && <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted }}>Showing {data?.returned_total ?? items.length} of {data?.matched_total ?? items.length} matched</span>}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowFilters(!showFilters)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:brightness-125" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }}>
            <Filter className="w-4 h-4" />{showFilters ? 'Hide Filters' : 'Filters'}
          </button>
          <button
            onClick={handleExportCSV}
            disabled={items.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:brightness-125 disabled:opacity-40"
            style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted, border: `1px solid ${ANALYSIS_BG.border}` }}
            title="Export to CSV"
          >
            <Download className="w-4 h-4" />CSV
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      {showFilters && (
        <div className="rounded-lg p-3 space-y-2" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
          {availLayerTypes.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs w-20" style={{ color: ANALYSIS_BG.textMuted }}>Layer type:</span>
              {availLayerTypes.map((lt) => (
                <button key={lt} onClick={() => toggleFilter('layer_types', lt)} className={`px-2 py-0.5 rounded text-xs border transition-colors ${filters.layer_types?.includes(lt) ? 'bg-violet-500/20 border-violet-400/50 text-violet-300' : ''}`}
                  style={!filters.layer_types?.includes(lt) ? { backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.textMuted } : {}}>
                  {LAYER_TYPE_LABELS[lt] || lt}
                </button>
              ))}
            </div>
          )}
          {availCrystals.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs w-20" style={{ color: ANALYSIS_BG.textMuted }}>Crystal:</span>
              {availCrystals.map((c) => (
                <button key={c} onClick={() => toggleFilter('crystal_materials', c)} className={`px-2 py-0.5 rounded text-xs border transition-colors ${filters.crystal_materials?.includes(c) ? 'bg-blue-500/20 border-blue-400/50 text-blue-300' : ''}`}
                  style={!filters.crystal_materials?.includes(c) ? { backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.textMuted } : {}}>
                  {c}
                </button>
              ))}
            </div>
          )}
          {availAging.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs w-20" style={{ color: ANALYSIS_BG.textMuted }}>Aging:</span>
              {availAging.map((a) => (
                <button key={a} onClick={() => toggleFilter('aging_states', a)} className={`px-2 py-0.5 rounded text-xs border transition-colors ${filters.aging_states?.includes(a) ? 'bg-amber-500/20 border-amber-400/50 text-amber-300' : ''}`}
                  style={!filters.aging_states?.includes(a) ? { backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.textMuted } : {}}>
                  {a}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs w-20" style={{ color: ANALYSIS_BG.textMuted }}>Temp (K):</span>
            <input type="number" placeholder="Min" value={tempMinDraft} onChange={e => setTempMinDraft(e.target.value)}
              className="w-20 text-xs rounded px-2 py-0.5" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }} />
            <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>-</span>
            <input type="number" placeholder="Max" value={tempMaxDraft} onChange={e => setTempMaxDraft(e.target.value)}
              className="w-20 text-xs rounded px-2 py-0.5" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text, border: `1px solid ${ANALYSIS_BG.border}` }} />
            <button onClick={applyTempFilter} className="px-2 py-0.5 rounded text-xs bg-blue-500/20 border border-blue-400/50 text-blue-300">Apply</button>
            <button onClick={resetTempFilter} className="px-2 py-0.5 rounded text-xs" style={{ backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.textMuted, border: `1px solid ${ANALYSIS_BG.border}` }}>Reset</button>
            {data?.temp_range && <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>Range: {data.temp_range[0]}–{data.temp_range[1]} K</span>}
          </div>
        </div>
      )}

      {/* Hover info (shared) */}
      <div className="min-h-[32px]">
        {(hovered1 || hovered2) && (() => {
          const h = hovered1 || hovered2
          return (
            <div className="flex flex-nowrap gap-2 text-xs overflow-x-auto" style={{ color: ANALYSIS_BG.text }}>
              {[
                h.exp_id,
                `Layer: ${LAYER_TYPE_LABELS[h.layer_type] || h.layer_type || '-'}`,
                `Crystal: ${h.crystal_material || '-'}`,
                `Binder: ${h.binder_type || '-'}${h.binder_type_secondary ? ' / ' + h.binder_type_secondary : ''}`,
                `Aging: ${h.aging_state || '-'}${h.aging_state_secondary ? ' / ' + h.aging_state_secondary : ''}`,
                `T: ${h.temperature_K != null ? Number(h.temperature_K).toFixed(0) + ' K' : '-'}`,
                h.adhesion_energy != null ? `Adhesion: ${Number(h.adhesion_energy).toFixed(1)} mJ/m\u00B2` : null,
                h.tensile_strength != null ? `Tensile: ${Number(h.tensile_strength).toFixed(1)} MPa` : null,
                h.ghg_emission != null ? `GHG: ${Number(h.ghg_emission).toFixed(3)}` : null,
              ].filter(Boolean).map((label) => (
                <span key={label} className="px-2 py-1 rounded whitespace-nowrap" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>{label}</span>
              ))}
            </div>
          )
        })()}
      </div>

      {/* Two charts side by side */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <ScatterChart
          items={items}
          defaultAxisX="temperature_K"
          defaultAxisY="crystal_material"
          defaultAxisZ="adhesion_energy"
          defaultColorBy="layer_type"
          title="Adhesion & Energy"
          hovered={hovered1}
          onHover={setHovered1}
        />
        <ScatterChart
          items={items}
          defaultAxisX="temperature_K"
          defaultAxisY="crystal_material"
          defaultAxisZ="tensile_strength"
          defaultColorBy="aging_state"
          title="Mechanical Properties"
          hovered={hovered2}
          onHover={setHovered2}
        />
      </div>
    </div>
  )
}
