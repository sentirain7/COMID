import api from './axiosInstance'

export const getMetrics = async (expId) => {
  const response = await api.get(`/metrics/${expId}`)
  return response.data
}

export const getExperimentThermo = async (expId, signal) => {
  const response = await api.get(`/experiments/${expId}/thermo`, { signal })
  return response.data
}

export const getCEDByAdditive = async (ffType = 'bulk_ff_gaff2') => {
  const response = await api.get(`/metrics/ced-by-additive?ff_type=${ffType}`)
  return response.data
}

export const getTemperatureScan = async (expId) => {
  const response = await api.get(`/metrics/temperature-scan/${expId}`)
  return response.data
}

export const getDensityTemperatureData = async (ffType = 'bulk_ff_gaff2') => {
  const response = await api.get(`/metrics/density-temperature?ff_type=${ffType}`)
  return response.data
}

export const getPropertyByTemperature = async (metricName, ffType = 'bulk_ff_gaff2', additiveMolId = null) => {
  const params = new URLSearchParams()
  params.append('ff_type', ffType)
  if (additiveMolId) params.append('additive_mol_id', additiveMolId)
  const response = await api.get(`/metrics/property-temperature/${metricName}?${params}`)
  return response.data
}

export const getPropertyByAdditive = async (metricName, ffType = 'bulk_ff_gaff2', temperatureK = null) => {
  const params = new URLSearchParams()
  params.append('ff_type', ffType)
  if (temperatureK) params.append('temperature_k', temperatureK)
  const response = await api.get(`/metrics/property-by-additive/${metricName}?${params}`)
  return response.data
}

export const getArrayMetricData = async (expId, metricName) => {
  const response = await api.get(`/experiments/${expId}/array-metric/${metricName}`)
  return response.data
}

export const getExperimentArrayMetrics = async (expId) => {
  const response = await api.get(`/experiments/${expId}/array-metrics`)
  return response.data
}

export const getArrayMetricCompare = async (expIds, metricName) => {
  const response = await api.post('/experiments/array-metric-compare', { exp_ids: expIds, metric_name: metricName })
  return response.data
}

export const getExperimentsWithArrayMetric = async (metricName) => {
  const response = await api.get(`/experiments/with-array-metric/${metricName}`)
  return response.data
}
