import api from './axiosInstance'

export const getChampionModel = async () => {
  const response = await api.get('/ml/models/champion')
  return response.data
}

export const getModelHistory = async ({ limit = 20, status } = {}) => {
  const params = new URLSearchParams()
  params.append('limit', limit)
  if (status) params.append('status', status)

  const response = await api.get(`/ml/models/history?${params}`)
  return response.data
}

export const retrainModel = async (payload = {}) => {
  const response = await api.post('/ml/models/retrain', payload)
  return response.data
}

export const promoteModel = async (versionId) => {
  const response = await api.post(`/ml/models/${versionId}/promote`)
  return response.data
}

export const rollbackModel = async () => {
  const response = await api.post('/ml/models/rollback')
  return response.data
}

export const checkModelDrift = async () => {
  const response = await api.get('/ml/drift/check')
  return response.data
}

export const getParityPlot = async (target) => {
  const response = await api.get(`/ml/diagnostics/parity?target=${encodeURIComponent(target)}`)
  return response.data
}

export const getFeatureImportance = async (target, topK = 15) => {
  const response = await api.get(`/ml/diagnostics/feature-importance?target=${encodeURIComponent(target)}&top_k=${topK}`)
  return response.data
}

export const getResiduals = async (target) => {
  const response = await api.get(`/ml/diagnostics/residuals?target=${encodeURIComponent(target)}`)
  return response.data
}

export const getLearningCurve = async (target) => {
  const response = await api.get(`/ml/diagnostics/learning-curve?target=${encodeURIComponent(target)}`)
  return response.data
}

export const getDataCoverage = async () => {
  const response = await api.get('/ml/diagnostics/data-coverage')
  return response.data
}

export const getDataQuality = async () => {
  const response = await api.get('/ml/diagnostics/data-quality')
  return response.data
}

export const getStructuralMLStatus = async () => {
  const response = await api.get('/ml/structural/status')
  return response.data
}

// V7 on-demand evaluation (XGB vs RF random repeats) — includes training, response may be delayed.
export const runStructuralEval = async (payload = {}) => {
  const response = await api.post('/ml/structural/evaluate', payload)
  return response.data
}

// V7 challenger training (default dry-run; register=true triggers registration/promotion decision).
export const runStructuralTrain = async (payload = {}) => {
  const response = await api.post('/ml/structural/train', payload)
  return response.data
}
