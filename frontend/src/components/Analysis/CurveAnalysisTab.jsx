import { useState, useMemo, lazy, Suspense } from 'react'
import { useExperimentsWithArrayMetric, useArrayMetricCompare } from '../../hooks/useApi'
import { CURVE_METRIC_TABS, ANALYSIS_BG } from '../../lib/constants'
import TabGroup from '../shared/TabGroup'
import ExperimentSelector from './ExperimentSelector'
import RdfCurveChart from '../Charts/RdfCurveChart'
import RdfPairCurveChart from '../Charts/RdfPairCurveChart'
import MsdCurveChart from '../Charts/MsdCurveChart'
import CohesiveEnergyDensityProfileChart from '../Charts/CohesiveEnergyDensityProfileChart'
import ThermoLogChart from '../Charts/ThermoLogChart'

const CurveSurface3D = lazy(() => import('./CurveSurface3D'))

const METRIC_CONFIG = {
  rdf_curve: {
    xKey: 'r',
    zKey: 'g_r',
    axisLabels: { x: 'r (\u00C5)', y: 'Temperature (K)', z: 'g(r)' },
    emptyMsg: 'No RDF data available. Run bulk property simulations to generate data.',
    supports3D: true,
  },
  rdf_pair_curve: {
    xKey: 'r',
    zKey: 'g_r',
    axisLabels: { x: 'r (\u00C5)', y: 'Temperature (K)', z: 'g(r)' },
    emptyMsg: 'No pair-type RDF data available. Run simulations with SARA group assignments.',
    singleExperiment: true,
    supports3D: false,
  },
  msd_curve: {
    xKey: 'time_ps',
    zKey: 'msd',
    axisLabels: { x: 'Time (ps)', y: 'Temperature (K)', z: 'MSD (\u00C5\u00B2)' },
    emptyMsg: 'No MSD data available. Run bulk property simulations to generate data.',
    supports3D: true,
  },
  cohesive_energy_density_profile: {
    xKey: 'layer_index',
    zKey: 'ced_MJ_m3',
    axisLabels: { x: 'Layer Index', y: 'Temperature (K)', z: 'CED (MJ/m\u00B3)' },
    emptyMsg: 'No cohesive energy density profile data available. Run layered structure experiments that persist layer-wise CED metrics.',
    supports3D: false,
  },
  thermo_log: {
    xKey: 'time_ps',
    zKey: 'temp',
    axisLabels: { x: 'Time (ps)', y: 'Temperature (K)', z: 'Value' },
    emptyMsg: 'No thermo log data available. Run simulations to generate data.',
    singleExperiment: true,
    supports3D: false,
  },
}

// Only show tabs marked as enabled in SSOT (constants.js)
const ACTIVE_CURVE_TABS = CURVE_METRIC_TABS.filter((t) => t.enabled !== false)

export default function CurveAnalysisTab() {
  const [activeMetric, setActiveMetric] = useState(ACTIVE_CURVE_TABS[0]?.key || 'rdf_curve')
  const [selectedIds, setSelectedIds] = useState([])
  const [show3D, setShow3D] = useState(false)

  // Fetch experiment list for the active metric
  const {
    data: experimentList,
    loading: listLoading,
    error: listError,
  } = useExperimentsWithArrayMetric(activeMetric)

  // Fetch compare data for selected experiments
  const {
    data: compareData,
    loading: compareLoading,
  } = useArrayMetricCompare(selectedIds, activeMetric)

  // Build chart-ready experiments array
  const chartExperiments = useMemo(() => {
    if (!compareData?.experiments) return []
    return compareData.experiments.map((exp) => ({
      expId: exp.exp_id,
      label: exp.label,
      columns: exp.columns || {},
      metadata: exp.metadata || {},
      temperature_k: null, // will be resolved from experiment list
    }))
  }, [compareData])

  // Enrich with temperature for 3D
  const enrichedExperiments = useMemo(() => {
    if (!chartExperiments.length || !experimentList?.length) return chartExperiments
    const tempMap = {}
    experimentList.forEach((e) => {
      tempMap[e.exp_id] = e.temperature_k
    })
    return chartExperiments.map((exp) => ({
      ...exp,
      temperature_k: tempMap[exp.expId] || null,
    }))
  }, [chartExperiments, experimentList])

  const config = METRIC_CONFIG[activeMetric] || METRIC_CONFIG.rdf_curve
  const maxSelection = config.singleExperiment ? 1 : 8
  const hasAllTemps = enrichedExperiments.length > 0 && enrichedExperiments.every((e) => e.temperature_k != null)

  const handleMetricChange = (key) => {
    setActiveMetric(key)
    setSelectedIds([])
    setShow3D(false)
  }

  const handleSelectionChange = (ids) => {
    if (config.singleExperiment) {
      // For single-experiment metrics, keep only the latest selection
      setSelectedIds(ids.slice(-1))
    } else {
      setSelectedIds(ids)
    }
  }

  const CHART_MAP = {
    rdf_curve: RdfCurveChart,
    rdf_pair_curve: RdfPairCurveChart,
    msd_curve: MsdCurveChart,
    cohesive_energy_density_profile: CohesiveEnergyDensityProfileChart,
    thermo_log: ThermoLogChart,
  }
  const ChartComponent = CHART_MAP[activeMetric] || RdfCurveChart

  return (
    <div className="space-y-4">
      {/* Sub-tab navigation */}
      <TabGroup
        tabs={ACTIVE_CURVE_TABS}
        activeTab={activeMetric}
        onTabChange={handleMetricChange}
      />

      <div className="grid grid-cols-12 gap-4">
        {/* Left: Experiment selector */}
        <div className="col-span-3">
          <ExperimentSelector
            experiments={experimentList || []}
            selectedIds={selectedIds}
            onSelectionChange={handleSelectionChange}
            loading={listLoading}
            error={listError}
            maxSelection={maxSelection}
          />
        </div>

        {/* Right: Chart area */}
        <div className="col-span-9">
          {selectedIds.length === 0 ? (
            <div
              className="rounded-lg border p-8 text-center text-sm h-[420px] flex items-center justify-center"
              style={{
                backgroundColor: ANALYSIS_BG.card,
                borderColor: ANALYSIS_BG.border,
                color: ANALYSIS_BG.textMuted,
              }}
            >
              {config.emptyMsg}
            </div>
          ) : (
            <div className="space-y-4">
              {/* 2D Chart */}
              <div
                className="rounded-lg border p-4 h-[420px] flex flex-col"
                style={{ backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border }}
              >
                <div className="flex items-center justify-between mb-2 flex-shrink-0">
                  <h3 className="text-sm font-medium" style={{ color: ANALYSIS_BG.text }}>
                    {ACTIVE_CURVE_TABS.find((t) => t.key === activeMetric)?.label || activeMetric}
                    {compareLoading && (
                      <span className="ml-2 text-xs text-slate-500">Loading...</span>
                    )}
                  </h3>
                  {config.supports3D && (
                    <button
                      onClick={() => hasAllTemps && setShow3D((prev) => !prev)}
                      disabled={!hasAllTemps}
                      className={`px-2 py-1 text-xs rounded border transition-colors ${
                        !hasAllTemps
                          ? 'opacity-40 cursor-not-allowed border-slate-600 text-slate-500'
                          : show3D
                            ? 'bg-purple-500/20 border-purple-400/40 text-purple-300'
                            : 'bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-300'
                      }`}
                      title={!hasAllTemps ? 'Temperature data missing for some experiments' : ''}
                    >
                      3D View
                    </button>
                  )}
                </div>
                <div className="flex-1 min-h-0">
                  <ChartComponent experiments={enrichedExperiments} />
                </div>
              </div>

              {/* 3D View (lazy loaded) */}
              {show3D && config.supports3D && hasAllTemps && enrichedExperiments.length > 0 && (
                <div
                  className="rounded-lg border"
                  style={{ backgroundColor: ANALYSIS_BG.card, borderColor: ANALYSIS_BG.border }}
                >
                  <div className="px-4 pt-3 pb-1">
                    <h3 className="text-sm font-medium" style={{ color: ANALYSIS_BG.text }}>
                      3D Temperature Stack
                    </h3>
                    <p className="text-xs mt-0.5" style={{ color: ANALYSIS_BG.textMuted }}>
                      Curves stacked by temperature. Drag to rotate, scroll to zoom.
                    </p>
                  </div>
                  <Suspense
                    fallback={
                      <div className="h-[400px] flex items-center justify-center text-xs text-slate-500">
                        Loading 3D view...
                      </div>
                    }
                  >
                    <CurveSurface3D
                      experiments={enrichedExperiments}
                      xKey={config.xKey}
                      zKey={config.zKey}
                      axisLabels={config.axisLabels}
                    />
                  </Suspense>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
