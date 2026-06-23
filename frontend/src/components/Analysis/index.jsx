import { useState, useMemo, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAnalysisEmbedding } from '../../hooks/useApi'
import { Sparkles, RefreshCw } from 'lucide-react'
import { ANALYSIS_BG } from '../../lib/constants'
import useThemeVersion from '../../hooks/useThemeVersion'
import { buildGraphFromPoints } from './graphUtils'
import TabGroup from '../shared/TabGroup'
import BulkPropertiesTab from './BulkPropertiesTab'
import LayeredAnalysisTab from './LayeredAnalysisTab'
import GHGAnalysisTab from './GHGAnalysisTab'
import TransitionsTab from './TransitionsTab'
import CurveAnalysisTab from './CurveAnalysisTab'
import ExplorerTab from './ExplorerTab'

const ANALYSIS_TABS = [
  { key: 'bulk', label: 'Bulk Properties' },
  { key: 'layered', label: 'Layered Structures' },
  { key: 'ghg', label: 'GHG & Sustainability' },
  { key: 'transitions', label: 'Composition Transitions' },
  { key: 'curves', label: 'Curve Analysis' },
  { key: 'explorer', label: 'Analysis Explorer' },
]

function Analysis() {
  useThemeVersion('analysis')
  const [activeTab, setActiveTab] = useState('bulk')
  const [demoDataEnabled, setDemoDataEnabled] = useState(false)

  const queryClient = useQueryClient()
  const { data: apiData, loading, error } = useAnalysisEmbedding('bulk_ff_gaff2', 60000)

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['analysis-embedding'] })
    queryClient.invalidateQueries({ queryKey: ['scatter3d'] })
    queryClient.invalidateQueries({ queryKey: ['binder-cell-xy-summary'] })
    queryClient.invalidateQueries({ queryKey: ['layered-analysis-3d'] })
    queryClient.invalidateQueries({ queryKey: ['property-temperature'] })
    queryClient.invalidateQueries({ queryKey: ['property-by-additive'] })
    queryClient.invalidateQueries({ queryKey: ['array-metric-compare'] })
    queryClient.invalidateQueries({ queryKey: ['experiments-with-array-metric'] })
    queryClient.invalidateQueries({ queryKey: ['explorer-catalog'] })
    queryClient.invalidateQueries({ queryKey: ['explorer-data'] })
    queryClient.invalidateQueries({ queryKey: ['explorer-aggregate'] })
  }, [queryClient])

  const propertyPoints = useMemo(() => {
    if (demoDataEnabled) {
      const binders = ['AAA1', 'AAK1', 'AAM1']
      const additives = ['none', 'SBS', 'PPA', 'SiO2', 'Lignin', 'WMA']
      const agingStates = ['non_aging', 'short_aging', 'long_aging']
      const points = []
      for (let i = 0; i < 42; i += 1) {
        const binder = binders[i % binders.length]
        const additive = additives[i % additives.length]
        const aging = agingStates[i % agingStates.length]
        const temperature = 233 + (i % 11) * 20
        const density = 0.9 + ((i * 11) % 26) / 100
        const ced = 255 + ((i * 19) % 180)
        points.push({
          exp_id: `demo_${String(i + 1).padStart(3, '0')}`,
          mol_id: `demo_${String(i + 1).padStart(3, '0')}`,
          mol_name: `Synthetic demo ${i + 1}`,
          category: ['saturate', 'aromatic', 'resin', 'asphaltene'][i % 4],
          binder_type: binder,
          additive,
          aging_state: aging,
          additive_wt: additive === 'none' ? 0 : 3 + (i % 5),
          temperature_k: temperature,
          density,
          ced,
          experiment_count: 1,
          is_synthetic: true,
          position: [
            ((temperature - 333) / (433 - 233)) * 12,
            ((density - 1.02) / 0.25) * 10,
            ((ced - 340) / 220) * 12,
          ],
          metrics: {
            density_impact: density - 1.02,
            ced_impact: ced - 340,
          },
        })
      }
      return points
    }

    if (!Array.isArray(apiData)) return []
    return apiData.filter((item) => {
      const temp = Number(item.temperature_k)
      const den = Number(item.density)
      const ced = Number(item.ced)
      return Number.isFinite(temp) && Number.isFinite(den) && Number.isFinite(ced)
    })
  }, [apiData, demoDataEnabled])

  const graphData = useMemo(() => buildGraphFromPoints(propertyPoints), [propertyPoints])

  return (
    <div className="h-full overflow-y-auto" style={{ backgroundColor: ANALYSIS_BG.container }}>
      {/* Header */}
      <div
        className="flex items-center justify-between p-6 sticky top-0 z-10"
        style={{ backgroundColor: ANALYSIS_BG.container, borderBottom: `1px solid ${ANALYSIS_BG.border}` }}
      >
        <div className="flex items-center gap-3">
          <Sparkles className="w-6 h-6 text-purple-400" />
          <div>
            <h1 className="text-2xl font-bold" style={{ color: ANALYSIS_BG.text }}>Analysis</h1>
            <p className="text-sm mt-1" style={{ color: ANALYSIS_BG.textMuted }}>
              Analyze property space and composition transitions.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRefresh}
            className="flex items-center gap-2 px-3 py-2 rounded-lg transition-colors hover:brightness-125"
            style={{ backgroundColor: ANALYSIS_BG.card, color: ANALYSIS_BG.text }}
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>

          <button
            onClick={() => setDemoDataEnabled((prev) => !prev)}
            className={`px-3 py-2 rounded-lg text-sm border transition-colors ${
              demoDataEnabled
                ? 'bg-amber-500/20 border-amber-400/40 text-amber-300'
                : 'hover:brightness-125'
            }`}
            style={demoDataEnabled ? {} : { backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border, color: ANALYSIS_BG.textMuted }}
          >
            Demo Data {demoDataEnabled ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      <div className="p-6">
        <TabGroup tabs={ANALYSIS_TABS} activeTab={activeTab} onTabChange={setActiveTab} />

        <div className="mt-4">
          {activeTab === 'bulk' && (
            <BulkPropertiesTab
              propertyPoints={propertyPoints}
              loading={loading}
              error={error}
              demoDataEnabled={demoDataEnabled}
            />
          )}
          {activeTab === 'layered' && <LayeredAnalysisTab />}
          {activeTab === 'ghg' && <GHGAnalysisTab />}
          {activeTab === 'transitions' && (
            <TransitionsTab
              graphData={graphData}
              loading={loading}
              demoDataEnabled={demoDataEnabled}
            />
          )}
          {activeTab === 'curves' && <CurveAnalysisTab />}
          {activeTab === 'explorer' && <ExplorerTab />}
        </div>
      </div>
    </div>
  )
}

export default Analysis
