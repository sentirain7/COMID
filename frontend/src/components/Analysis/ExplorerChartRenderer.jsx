/**
 * Explorer Chart Renderer: dispatches to appropriate chart based on type.
 *
 * Supported chart types (must match catalog.py _CHART_TYPES_ALL):
 *   scatter  — 2D SVG scatter plot
 *   line     — 2D SVG scatter + ordered polyline per series
 *   bar      — 2D SVG bar chart from aggregate data
 *   scatter3d — 3D @react-three/fiber scatter (reuses ScatterPrimitives)
 *   table    — raw data table
 */
import { useMemo } from 'react'
import { Canvas } from '@react-three/fiber'
import { ANALYSIS_BG } from '../../lib/constants'
import { formatMetricValue } from './explorerUtils'
import { ScatterCanvas, ScatterPoint, AxisLines } from './ScatterPrimitives'
import { normalize, encodeCategorical } from './layeredScatterUtils'

const COLORS = ['#60a5fa', '#f59e0b', '#f43f5e', '#34d399', '#a78bfa', '#fb923c', '#22d3ee', '#e879f9']

// ─── 2D Scatter / Line Chart ──────────────────────────────────────────────
function ScatterLineChart({ rows, xKey, yKey, seriesKey, drawLines = false }) {
  const series = useMemo(() => {
    const groups = {}
    rows.forEach(r => {
      const s = seriesKey ? String(r[seriesKey] ?? 'other') : 'all'
      if (!groups[s]) groups[s] = []
      groups[s].push(r)
    })
    // For line chart: sort each series by xKey asc, then by id
    if (drawLines) {
      Object.values(groups).forEach(pts => {
        pts.sort((a, b) => {
          const xa = Number(a[xKey]) || 0, xb = Number(b[xKey]) || 0
          if (xa !== xb) return xa - xb
          return String(a.exp_id || a.mol_id || '').localeCompare(String(b.exp_id || b.mol_id || ''))
        })
      })
    }
    return Object.entries(groups)
  }, [rows, seriesKey, drawLines, xKey])

  if (!rows.length) return <div className="text-center py-8" style={{ color: ANALYSIS_BG.textMuted }}>No data</div>

  const allX = rows.map(r => Number(r[xKey])).filter(n => isFinite(n))
  const allY = rows.map(r => Number(r[yKey])).filter(n => isFinite(n))
  if (!allX.length || !allY.length) return <div className="text-center py-8" style={{ color: ANALYSIS_BG.textMuted }}>No numeric data for axes</div>

  const [xMin, xMax] = [Math.min(...allX), Math.max(...allX)]
  const [yMin, yMax] = [Math.min(...allY), Math.max(...allY)]
  const xRange = xMax - xMin || 1
  const yRange = yMax - yMin || 1
  const W = 600, H = 360, PAD = 50

  const toX = v => PAD + ((v - xMin) / xRange) * (W - PAD - 10)
  const toY = v => H - PAD - ((v - yMin) / yRange) * (H - PAD - 10)

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 400 }}>
        <line x1={PAD} y1={H - PAD} x2={W - 10} y2={H - PAD} stroke={ANALYSIS_BG.border} />
        <line x1={PAD} y1={10} x2={PAD} y2={H - PAD} stroke={ANALYSIS_BG.border} />
        <text x={W / 2} y={H - 5} fill={ANALYSIS_BG.textMuted} fontSize="11" textAnchor="middle">{xKey}</text>
        <text x={12} y={H / 2} fill={ANALYSIS_BG.textMuted} fontSize="11" textAnchor="middle" transform={`rotate(-90,12,${H / 2})`}>{yKey}</text>

        {series.map(([name, pts], si) => {
          const color = COLORS[si % COLORS.length]
          const coords = pts.map(r => {
            const x = toX(Number(r[xKey]))
            const y = toY(Number(r[yKey]))
            return isFinite(x) && isFinite(y) ? { x, y, r } : null
          }).filter(Boolean)

          return (
            <g key={name}>
              {/* Polyline for line chart */}
              {drawLines && coords.length > 1 && (
                <polyline
                  points={coords.map(c => `${c.x},${c.y}`).join(' ')}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.5}
                  opacity={0.6}
                />
              )}
              {/* Points */}
              {coords.map((c, i) => (
                <circle key={i} cx={c.x} cy={c.y} r={3} fill={color} opacity={0.8}>
                  <title>{c.r.exp_id || c.r.mol_id}: {xKey}={formatMetricValue(c.r[xKey])}, {yKey}={formatMetricValue(c.r[yKey])}</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
      {seriesKey && (
        <div className="flex gap-3 mt-1 flex-wrap">
          {series.map(([name], si) => (
            <span key={name} className="flex items-center gap-1 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[si % COLORS.length] }} />
              {name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── 3D Scatter Chart ──────────────────────────────────────────────────────
function Scatter3DChart({ rows, xKey, yKey, zKey, seriesKey }) {
  const { points, labels } = useMemo(() => {
    if (!rows?.length) return { points: [], labels: {} }

    const rawX = rows.map(r => Number(r[xKey]))
    const rawY = rows.map(r => Number(r[yKey]))
    const rawZ = rows.map(r => Number(r[zKey || xKey]))

    const xIsNum = rawX.every(n => isFinite(n))
    const yIsNum = rawY.every(n => isFinite(n))
    const zIsNum = rawZ.every(n => isFinite(n))

    const posX = xIsNum ? normalize(rawX, 12) : encodeCategorical(rows.map(r => String(r[xKey] ?? '')), 12, rows, xKey).encoded
    const posY = yIsNum ? normalize(rawY, 10) : encodeCategorical(rows.map(r => String(r[yKey] ?? '')), 10, rows, yKey).encoded
    const posZ = zIsNum ? normalize(rawZ, 12) : encodeCategorical(rows.map(r => String(r[zKey || xKey] ?? '')), 12, rows, zKey || xKey).encoded

    const pts = rows.map((r, i) => ({
      ...r,
      position: [posX[i] || 0, posY[i] || 0, posZ[i] || 0],
      _seriesKey: seriesKey ? String(r[seriesKey] ?? 'other') : 'all',
    }))

    return { points: pts, labels: { x: xKey, y: yKey, z: zKey || xKey } }
  }, [rows, xKey, yKey, zKey, seriesKey])

  const seriesNames = useMemo(() => [...new Set(points.map(p => p._seriesKey))].sort(), [points])

  if (!points.length) return <div className="text-center py-8" style={{ color: ANALYSIS_BG.textMuted }}>No data for 3D scatter</div>

  return (
    <div>
      <div className="relative h-[420px] rounded-lg overflow-hidden" style={{ backgroundColor: ANALYSIS_BG.containerAlpha, border: `1px solid ${ANALYSIS_BG.border}` }}>
        <Canvas camera={{ position: [11, 10, 11], fov: 50 }}>
          <ScatterCanvas>
            {points.map((item, i) => {
              const si = seriesNames.indexOf(item._seriesKey)
              return (
                <ScatterPoint
                  key={item.exp_id || item.mol_id || i}
                  item={item}
                  isHovered={false}
                  onHover={() => {}}
                  color={COLORS[si % COLORS.length]}
                />
              )
            })}
            <AxisLines labels={labels} />
          </ScatterCanvas>
        </Canvas>
      </div>
      {seriesKey && (
        <div className="flex gap-3 mt-1 flex-wrap">
          {seriesNames.map((name, si) => (
            <span key={name} className="flex items-center gap-1 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[si % COLORS.length] }} />
              {name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Bar Chart ──────────────────────────────────────────────────────────────
function BarChart({ aggregateData, metric }) {
  if (!aggregateData?.groups?.length) return <div className="text-center py-8" style={{ color: ANALYSIS_BG.textMuted }}>No data</div>

  const { groups, series, values } = aggregateData
  const allVals = values.flat().filter(v => v != null)
  const maxVal = Math.max(...allVals, 1e-9)
  const barWidth = Math.min(40, 500 / (groups.length * (series?.length || 1)))

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${Math.max(600, groups.length * barWidth * (series?.length || 1) * 1.5 + 80)} 360`} className="w-full" style={{ maxHeight: 400 }}>
        {groups.map((g, gi) => {
          const gx = 60 + gi * barWidth * (series?.length || 1) * 1.5
          return (
            <g key={g}>
              <text x={gx + barWidth * (series?.length || 1) * 0.5} y={340} fill={ANALYSIS_BG.textMuted} fontSize="10" textAnchor="middle">{g.length > 12 ? g.slice(0, 12) + '...' : g}</text>
              {(series || ['value']).map((s, si) => {
                const val = values[gi]?.[si]
                if (val == null) return null
                const h = (val / maxVal) * 280
                return (
                  <rect key={s} x={gx + si * barWidth} y={320 - h} width={barWidth - 2} height={h} fill={COLORS[si % COLORS.length]} rx={2} opacity={0.85}>
                    <title>{g} / {s}: {formatMetricValue(val)}</title>
                  </rect>
                )
              })}
            </g>
          )
        })}
        <text x={30} y={20} fill={ANALYSIS_BG.textMuted} fontSize="11">{metric}</text>
      </svg>
      {series && series.length > 1 && (
        <div className="flex gap-3 mt-1 flex-wrap">
          {series.map((s, si) => (
            <span key={s} className="flex items-center gap-1 text-xs" style={{ color: ANALYSIS_BG.textMuted }}>
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[si % COLORS.length] }} />
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Data Table ──────────────────────────────────────────────────────────────
function DataTable({ rows, columns }) {
  if (!rows?.length) return <div className="text-center py-4" style={{ color: ANALYSIS_BG.textMuted }}>No data</div>

  const cols = columns || Object.keys(rows[0] || {}).slice(0, 12)

  return (
    <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
      <table className="w-full text-xs" style={{ color: ANALYSIS_BG.text }}>
        <thead>
          <tr>
            {cols.map(c => (
              <th key={c} className="px-2 py-1 text-center sticky top-0" style={{ backgroundColor: ANALYSIS_BG.card, borderBottom: `1px solid ${ANALYSIS_BG.border}` }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 200).map((r, i) => (
            <tr key={i} className="hover:brightness-125 text-center" style={{ backgroundColor: i % 2 === 0 ? 'transparent' : ANALYSIS_BG.containerAlpha }}>
              {cols.map(c => (
                <td key={c} className="px-2 py-0.5" style={{ borderBottom: `1px solid ${ANALYSIS_BG.border}22` }}>
                  {formatMetricValue(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Main Dispatcher ─────────────────────────────────────────────────────────
export default function ExplorerChartRenderer({ chartType, rows, aggregateData, xAxis, yAxis, seriesAxis, metric, catalog }) {
  const dims = catalog?.dimensions?.map(d => d.key) || []
  const mets = catalog?.metrics?.map(m => m.key) || []
  const tableCols = [...new Set([...dims.slice(0, 4), ...mets.slice(0, 4)])]

  if (chartType === 'table') {
    return <DataTable rows={rows} columns={tableCols} />
  }

  if (chartType === 'bar' && aggregateData) {
    return <BarChart aggregateData={aggregateData} metric={yAxis || metric} />
  }

  if (chartType === 'scatter') {
    return <ScatterLineChart rows={rows || []} xKey={xAxis} yKey={yAxis} seriesKey={seriesAxis} drawLines={false} />
  }

  if (chartType === 'line') {
    return <ScatterLineChart rows={rows || []} xKey={xAxis} yKey={yAxis} seriesKey={seriesAxis} drawLines={true} />
  }

  if (chartType === 'scatter3d') {
    return <Scatter3DChart rows={rows || []} xKey={xAxis} yKey={yAxis} zKey={seriesAxis || xAxis} seriesKey={seriesAxis} />
  }

  return <DataTable rows={rows} columns={tableCols} />
}
