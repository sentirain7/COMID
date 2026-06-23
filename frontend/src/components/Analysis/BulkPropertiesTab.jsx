/**
 * Analysis Tab 1: Bulk Properties
 *
 * Contains: 3D Property Embedding + Property vs Temperature + Property by Additive.
 * All content moved from the original Analysis/index.jsx sections 1, 4, 5.
 */

import { useState, useMemo } from 'react'
import { Sparkles, Info, TrendingUp, Layers, Download } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import { exportChartToCSV } from '../../lib/csvExport'
import BinderPropertyViews from './BinderPropertyViews'
import TemperaturePropertyChart from '../Charts/TemperaturePropertyChart'
import AdditiveImpactChart from '../Charts/AdditiveImpactChart'

export default function BulkPropertiesTab({ propertyPoints, loading, error, demoDataEnabled }) {
  const [hoveredMolecule, setHoveredMolecule] = useState(null)

  const binderTypes = useMemo(
    () => [...new Set(propertyPoints.map((p) => p.binder_type).filter(Boolean))],
    [propertyPoints]
  )
  const additiveTypes = useMemo(
    () => [...new Set(propertyPoints.map((p) => p.additive).filter(Boolean))],
    [propertyPoints]
  )

  const handleExportEmbeddingCSV = () => {
    if (!propertyPoints.length) return
    const exportData = propertyPoints.map(p => ({
      exp_id: p.exp_id || p.mol_id || '',
      binder_type: p.binder_type || '',
      additive: p.additive || 'none',
      additive_wt: p.additive_wt || 0,
      aging_state: p.aging_state || 'non_aging',
      temperature_k: p.temperature_k || 0,
      density: p.density || 0,
      cohesive_energy_density: p.ced || 0,
      viscosity: p.viscosity || '',
      is_synthetic: p.is_synthetic ? 'true' : 'false',
    }))
    exportChartToCSV(
      exportData,
      ['exp_id', 'binder_type', 'additive', 'additive_wt', 'aging_state', 'temperature_k', 'density', 'cohesive_energy_density', 'viscosity', 'is_synthetic'],
      '3d_embedding_data',
      {
        exp_id: 'Experiment ID',
        binder_type: 'Binder Type',
        additive: 'Additive',
        additive_wt: 'Additive wt%',
        aging_state: 'Aging State',
        temperature_k: 'Temperature (K)',
        density: 'Density (g/cm3)',
        cohesive_energy_density: 'CED (MJ/m3)',
        viscosity: 'Viscosity (mPa.s)',
        is_synthetic: 'Is Synthetic',
      }
    )
  }

  return (
    <div className="space-y-6">
      {/* 3D Embedding */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-400" />
            <h2 className="text-lg font-medium text-white">3D Property Embedding</h2>
            {demoDataEnabled && (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded text-xs">
                <Info className="w-3 h-3" />Synthetic
              </span>
            )}
          </div>
          <button
            onClick={handleExportEmbeddingCSV}
            disabled={propertyPoints.length === 0}
            className="px-2 py-1 text-xs rounded border flex items-center gap-1 transition-colors hover:brightness-125 disabled:opacity-40"
            style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted, borderColor: ANALYSIS_BG.border }}
            title="Export to CSV"
          >
            <Download className="w-3 h-3" />
            CSV
          </button>
        </div>

        <div className="relative">
          {propertyPoints.length > 0 ? (
            <BinderPropertyViews
              points={propertyPoints}
              hovered={hoveredMolecule}
              onHover={setHoveredMolecule}
            />
          ) : error ? (
            <div className="h-[420px] flex items-center justify-center rounded-lg text-red-300" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
              Failed to load embedding data.
            </div>
          ) : !loading ? (
            <div className="h-[420px] flex items-center justify-center rounded-lg" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}`, color: ANALYSIS_BG.textMuted }}>
              No completed binder-cell embedding data yet.
            </div>
          ) : (
            <div className="h-[420px] flex items-center justify-center rounded-lg" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}`, color: ANALYSIS_BG.textMuted }}>
              Loading visualization...
            </div>
          )}
        </div>

        <div className="flex items-center gap-6 mt-3 text-sm" style={{ color: ANALYSIS_BG.textMuted }}>
          <span>Experiments: <span className="font-medium" style={{ color: ANALYSIS_BG.text }}>{propertyPoints.length}</span></span>
          <span>Binder types: <span className="font-medium" style={{ color: ANALYSIS_BG.text }}>{binderTypes.length}</span></span>
          <span>Additives: <span className="font-medium" style={{ color: ANALYSIS_BG.text }}>{additiveTypes.length}</span></span>
        </div>

        <div className="mt-3 min-h-[32px]">
          {hoveredMolecule ? (
            <div className="flex flex-nowrap gap-2 text-xs overflow-x-auto" style={{ color: ANALYSIS_BG.text }}>
              {[
                hoveredMolecule.exp_id || hoveredMolecule.mol_id,
                `Binder: ${hoveredMolecule.binder_type || '-'}`,
                `Additive: ${hoveredMolecule.additive || 'none'}${hoveredMolecule.additive_wt ? ` (${hoveredMolecule.additive_wt}wt%)` : ''}`,
                `Aging: ${hoveredMolecule.aging_state || 'NA'}`,
                `T: ${Number(hoveredMolecule.temperature_k || 0).toFixed(1)} K`,
                `Density: ${Number(hoveredMolecule.density || 0).toFixed(4)}`,
                `CED: ${Number(hoveredMolecule.ced || 0).toFixed(3)}`,
              ].map((label) => (
                <span key={label} className="px-2 py-1 rounded whitespace-nowrap" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>{label}</span>
              ))}
              {hoveredMolecule.is_synthetic && (
                <span className="px-2 py-1 rounded whitespace-nowrap bg-amber-500/20 border border-amber-400/30 text-amber-300">Synthetic</span>
              )}
            </div>
          ) : (
            <div className="text-xs py-1" style={{ color: ANALYSIS_BG.textMuted, opacity: 0.4 }}>
              Hover over a point to see details
            </div>
          )}
        </div>
      </section>

      {/* Property vs Temperature & Property by Additive - Side by Side */}
      <div className="grid grid-cols-2 gap-6">
        <section className="min-h-[420px]">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-medium text-white">Property vs Temperature</h2>
          </div>
          <div className="h-[380px]">
            <TemperaturePropertyChart ffType="bulk_ff_gaff2" />
          </div>
        </section>

        <section className="min-h-[420px]">
          <div className="flex items-center gap-2 mb-4">
            <Layers className="w-5 h-5 text-green-400" />
            <h2 className="text-lg font-medium text-white">Property by Additive</h2>
          </div>
          <div className="h-[380px]">
            <AdditiveImpactChart ffType="bulk_ff_gaff2" />
          </div>
        </section>
      </div>
    </div>
  )
}
