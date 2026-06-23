/**
 * GHG Emission by Group — bar chart + summary statistics section.
 *
 * Extracted from TransitionsTab to reduce god-component size.
 */

import { useState, useMemo } from 'react'
import { Leaf, Download } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import { exportChartToCSV } from '../../lib/csvExport'
import { useScatter3D } from '../../hooks/useApi'
import { GHG_GROUP_OPTIONS, formatGHG, computeGhgGroupedData, computeChartConfig } from './transitionHelpers'

export default function GHGByGroupSection() {
  const [ghgGroupBy, setGhgGroupBy] = useState('additive')

  // Fetch GHG data using scatter3D API (all axes as density to get GHG as z)
  const { data: ghgData, loading: ghgLoading, error: ghgError } = useScatter3D(
    'density', 'cohesive_energy_density', 'ghg_emission', 'bulk_ff_gaff2', 60000
  )

  // Group GHG data by selected category and calculate statistics
  const ghgGroupedData = useMemo(
    () => computeGhgGroupedData(ghgData, ghgGroupBy),
    [ghgData, ghgGroupBy]
  )

  // Calculate bar heights with baseline adjustment for better comparison
  const chartConfig = useMemo(
    () => computeChartConfig(ghgGroupedData),
    [ghgGroupedData]
  )

  const handleExportGhgCSV = () => {
    if (!chartConfig.bars.length) return
    const exportData = chartConfig.bars.map(bar => ({
      group: bar.label,
      mean_ghg: bar.mean,
      std: bar.std,
      min: bar.min,
      max: bar.max,
      sample_count: bar.count,
      deviation_from_mean_pct: bar.deviation,
    }))
    const filename = `ghg_emission_by_${ghgGroupBy}`
    exportChartToCSV(
      exportData,
      ['group', 'mean_ghg', 'std', 'min', 'max', 'sample_count', 'deviation_from_mean_pct'],
      filename,
      {
        group: `${GHG_GROUP_OPTIONS.find(o => o.value === ghgGroupBy)?.label || ghgGroupBy}`,
        mean_ghg: 'Mean GHG (kg CO2-eq/kg)',
        std: 'Std Dev',
        min: 'Min',
        max: 'Max',
        sample_count: 'Sample Count',
        deviation_from_mean_pct: 'Deviation from Mean (%)',
      }
    )
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Leaf className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-medium text-white">GHG Emission by Group</h2>
          <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted }}>
            kg CO₂-eq/kg
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {GHG_GROUP_OPTIONS.map((option) => (
            <button
              key={option.value}
              onClick={() => setGhgGroupBy(option.value)}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${ghgGroupBy === option.value ? 'bg-emerald-500/20 border-emerald-400/50 text-emerald-300' : 'hover:brightness-125'}`}
              style={ghgGroupBy !== option.value ? { backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted, borderColor: ANALYSIS_BG.border } : {}}
            >
              {option.label}
            </button>
          ))}
          <button
            onClick={handleExportGhgCSV}
            disabled={chartConfig.bars.length === 0}
            className="px-2 py-1.5 text-sm rounded-lg border flex items-center gap-1 transition-colors hover:brightness-125 disabled:opacity-40"
            style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.textMuted, borderColor: ANALYSIS_BG.border }}
            title="Export to CSV"
          >
            <Download className="w-3 h-3" />
            CSV
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[3fr_2fr] gap-4">
        {/* Bar Chart */}
        <div className="rounded-lg p-4" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
          {ghgLoading ? (
            <div className="h-[320px] flex items-center justify-center" style={{ color: ANALYSIS_BG.textMuted }}>Loading GHG data...</div>
          ) : ghgError ? (
            <div className="h-[320px] flex items-center justify-center text-red-300">Failed to load GHG data.</div>
          ) : chartConfig.bars.length === 0 ? (
            <div className="h-[320px] flex items-center justify-center" style={{ color: ANALYSIS_BG.textMuted }}>No GHG emission data available.</div>
          ) : (
            <div className="space-y-4">
              <div className="text-sm" style={{ color: ANALYSIS_BG.textMuted }}>
                Average GHG emission grouped by {ghgGroupBy}. Bars show relative comparison (baseline adjusted).
              </div>
              <div className="h-[260px] flex items-end gap-3">
                {chartConfig.bars.map((bar) => (
                  <div key={bar.key} className="flex-1 min-w-0 flex flex-col items-center gap-2 group relative">
                    {/* Value label */}
                    <div className="text-xs font-medium text-white">{formatGHG(bar.mean)}</div>

                    {/* Deviation indicator */}
                    <div className={`text-[10px] font-medium ${bar.isAboveMean ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {bar.deviation >= 0 ? '+' : ''}{bar.deviation.toFixed(1)}%
                    </div>

                    {/* Bar */}
                    <div className="w-full h-[180px] flex items-end">
                      <div
                        className={`w-full rounded-t-md border transition-all ${bar.isAboveMean ? 'border-rose-400/30 bg-gradient-to-t from-rose-500/70 to-rose-300/50' : 'border-emerald-400/30 bg-gradient-to-t from-emerald-500/70 to-emerald-300/50'}`}
                        style={{ height: `${bar.heightPct}%` }}
                      />
                    </div>

                    {/* Label */}
                    <div className="text-xs font-medium text-center text-slate-100 break-all max-w-full truncate" title={bar.label}>
                      {bar.label}
                    </div>

                    {/* Sample count */}
                    <div className="text-[11px] text-center" style={{ color: ANALYSIS_BG.textMuted }}>
                      n={bar.count}
                    </div>

                    {/* Hover tooltip */}
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-10">
                      <div className="rounded-lg px-3 py-2 text-xs whitespace-nowrap shadow-lg" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>
                        <div className="font-medium mb-1" style={{ color: ANALYSIS_BG.text }}>{bar.label}</div>
                        <div style={{ color: ANALYSIS_BG.textMuted }}>Mean: {formatGHG(bar.mean)} kg CO₂-eq/kg</div>
                        <div style={{ color: ANALYSIS_BG.textMuted }}>Min: {formatGHG(bar.min)} | Max: {formatGHG(bar.max)}</div>
                        <div style={{ color: ANALYSIS_BG.textMuted }}>Std: ±{formatGHG(bar.std)}</div>
                        <div style={{ color: ANALYSIS_BG.textMuted }}>Samples: {bar.count}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Baseline indicator */}
              <div className="flex items-center justify-between text-[10px]" style={{ color: ANALYSIS_BG.textMuted }}>
                <span>Baseline: {formatGHG(chartConfig.baseline)} (90% of min)</span>
                <span>Range: {formatGHG(chartConfig.range)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Summary Statistics */}
        <div className="rounded-lg p-4 space-y-3" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-white">GHG Statistics</h3>
            <span className="text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
              samples: {ghgGroupedData.globalStats?.total || 0}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-1 gap-2">
            <div className="rounded-lg p-3" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>
              <div className="text-xs mb-1" style={{ color: ANALYSIS_BG.textMuted }}>Global Mean GHG</div>
              <div className="text-lg font-semibold" style={{ color: ANALYSIS_BG.text }}>
                {formatGHG(ghgGroupedData.globalStats?.mean)}
              </div>
              <div className="text-[11px]" style={{ color: ANALYSIS_BG.textMuted }}>kg CO₂-eq/kg</div>
            </div>

            <div className="rounded-lg p-3" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>
              <div className="text-xs mb-1" style={{ color: ANALYSIS_BG.textMuted }}>Min / Max GHG</div>
              <div className="text-lg font-semibold" style={{ color: ANALYSIS_BG.text }}>
                {formatGHG(ghgGroupedData.globalStats?.min)} / {formatGHG(ghgGroupedData.globalStats?.max)}
              </div>
              <div className="text-[11px]" style={{ color: ANALYSIS_BG.textMuted }}>kg CO₂-eq/kg</div>
            </div>

            <div className="rounded-lg p-3" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>
              <div className="text-xs mb-1" style={{ color: ANALYSIS_BG.textMuted }}>Best Group ({ghgGroupBy})</div>
              <div className="text-lg font-semibold text-emerald-400">
                {chartConfig.bars[0]?.label || '-'}
              </div>
              <div className="text-[11px]" style={{ color: ANALYSIS_BG.textMuted }}>
                {chartConfig.bars[0] ? `${formatGHG(chartConfig.bars[0].mean)} kg CO₂-eq/kg` : '-'}
              </div>
            </div>

            <div className="rounded-lg p-3" style={{ backgroundColor: ANALYSIS_BG.card, border: `1px solid ${ANALYSIS_BG.border}` }}>
              <div className="text-xs mb-1" style={{ color: ANALYSIS_BG.textMuted }}>Groups Compared</div>
              <div className="text-lg font-semibold" style={{ color: ANALYSIS_BG.text }}>
                {chartConfig.bars.length}
              </div>
              <div className="text-[11px]" style={{ color: ANALYSIS_BG.textMuted }}>
                {GHG_GROUP_OPTIONS.find(o => o.value === ghgGroupBy)?.label || ghgGroupBy} categories
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="pt-2 border-t" style={{ borderColor: ANALYSIS_BG.border }}>
            <div className="text-xs mb-2" style={{ color: ANALYSIS_BG.textMuted }}>Color Legend:</div>
            <div className="flex items-center gap-4 text-xs">
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded bg-gradient-to-t from-emerald-500/70 to-emerald-300/50 border border-emerald-400/30" />
                <span style={{ color: ANALYSIS_BG.textMuted }}>Below mean</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded bg-gradient-to-t from-rose-500/70 to-rose-300/50 border border-rose-400/30" />
                <span style={{ color: ANALYSIS_BG.textMuted }}>Above mean</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
