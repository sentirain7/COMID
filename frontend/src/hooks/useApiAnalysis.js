import { useQuery } from '@tanstack/react-query'
import { wrapQuery } from './useApiShared'

/**
 * Hook for analysis embedding data (3D visualization).
 */
export function useAnalysisEmbedding(ffType = 'bulk_ff_gaff2', interval = 60000) {
  const query = useQuery({
    queryKey: ['analysis-embedding', ffType],
    queryFn: async () => {
      const { getAnalysisEmbedding } = await import('../api/client')
      return getAnalysisEmbedding(ffType)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for grouped binder-cell XY size summary and metric overview.
 */
export function useBinderCellXYSummary(groupBy = 'binder', ffType = 'bulk_ff_gaff2', interval = 60000) {
  const query = useQuery({
    queryKey: ['binder-cell-xy-summary', groupBy, ffType],
    queryFn: async () => {
      const { getBinderCellXYSummary } = await import('../api/client')
      return getBinderCellXYSummary(groupBy, ffType)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for molecule impact analysis.
 */
export function useMoleculeImpact(ffType = 'bulk_ff_gaff2', interval = 60000) {
  const query = useQuery({
    queryKey: ['molecule-impact', ffType],
    queryFn: async () => {
      const { getAnalysisMoleculeImpact } = await import('../api/client')
      return getAnalysisMoleculeImpact(ffType)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for Density vs Temperature data.
 */
export function useDensityTemperature(ffType = 'bulk_ff_gaff2', interval = 30000) {
  const query = useQuery({
    queryKey: ['density-temperature', ffType],
    queryFn: async () => {
      const { getDensityTemperatureData } = await import('../api/client')
      return getDensityTemperatureData(ffType)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for generic 3-axis scatter data (supports GHG emission axis).
 */
export function useScatter3D(axisX = 'density', axisY = 'cohesive_energy_density', axisZ = 'ghg_emission', ffType = 'bulk_ff_gaff2', interval = 60000) {
  const query = useQuery({
    queryKey: ['scatter3d', axisX, axisY, axisZ, ffType],
    queryFn: async () => {
      const { getScatter3D } = await import('../api/client')
      return getScatter3D(axisX, axisY, axisZ, ffType)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for CED by additive data.
 */
export function useCEDByAdditive(ffType = 'bulk_ff_gaff2', interval = 30000) {
  const query = useQuery({
    queryKey: ['ced-by-additive', ffType],
    queryFn: async () => {
      const { getCEDByAdditive } = await import('../api/client')
      return getCEDByAdditive(ffType)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
  })

  return wrapQuery(query)
}

/**
 * Hook for property by temperature data.
 */
export function usePropertyByTemperature(metricName, { ffType = 'bulk_ff_gaff2', additiveMolId = null } = {}, interval = 30000) {
  const query = useQuery({
    queryKey: ['property-temperature', metricName, ffType, additiveMolId],
    queryFn: async () => {
      const { getPropertyByTemperature } = await import('../api/client')
      return getPropertyByTemperature(metricName, ffType, additiveMolId)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
    enabled: Boolean(metricName),
  })

  return wrapQuery(query)
}

/**
 * Hook for property by additive data.
 */
export function usePropertyByAdditive(metricName, { ffType = 'bulk_ff_gaff2', temperatureK = null } = {}, interval = 30000) {
  const query = useQuery({
    queryKey: ['property-by-additive', metricName, ffType, temperatureK],
    queryFn: async () => {
      const { getPropertyByAdditive } = await import('../api/client')
      return getPropertyByAdditive(metricName, ffType, temperatureK)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
    enabled: Boolean(metricName),
  })

  return wrapQuery(query)
}

// =============================================================================
// Curve Analysis (Array Metric)
// =============================================================================

/**
 * Hook for listing experiments that have a specific array metric.
 */
export function useExperimentsWithArrayMetric(metricName, interval = 60000) {
  const query = useQuery({
    queryKey: ['experiments-with-array-metric', metricName],
    queryFn: async () => {
      const { getExperimentsWithArrayMetric } = await import('../api/client')
      return getExperimentsWithArrayMetric(metricName)
    },
    refetchInterval: interval,
    refetchIntervalInBackground: false,
    enabled: Boolean(metricName),
  })

  return wrapQuery(query)
}

/**
 * Hook for loading array metric data for a single experiment.
 */
export function useArrayMetricData(expId, metricName) {
  const query = useQuery({
    queryKey: ['array-metric-data', expId, metricName],
    queryFn: async () => {
      const { getArrayMetricData } = await import('../api/client')
      return getArrayMetricData(expId, metricName)
    },
    enabled: Boolean(expId) && Boolean(metricName),
  })

  return wrapQuery(query)
}

/**
 * Hook for listing array metrics stored for a single experiment.
 */
export function useExperimentArrayMetrics(expId) {
  const query = useQuery({
    queryKey: ['experiment-array-metrics', expId],
    queryFn: async () => {
      const { getExperimentArrayMetrics } = await import('../api/client')
      return getExperimentArrayMetrics(expId)
    },
    enabled: Boolean(expId),
  })

  return wrapQuery(query)
}

/**
 * Hook for comparing array metric data across experiments.
 */
export function useArrayMetricCompare(expIds, metricName) {
  const query = useQuery({
    queryKey: ['array-metric-compare', metricName, ...(expIds || [])],
    queryFn: async () => {
      const { getArrayMetricCompare } = await import('../api/client')
      return getArrayMetricCompare(expIds, metricName)
    },
    enabled: Boolean(metricName) && Array.isArray(expIds) && expIds.length > 0,
  })

  return wrapQuery(query)
}
