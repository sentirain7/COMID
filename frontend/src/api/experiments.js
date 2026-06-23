import api from './axiosInstance'

export const listExperiments = async ({ status, tier, limit = 100, exclude_layered, study_type, additive_mol_id, temperature_min, temperature_max, additive_type, e_intra_method } = {}) => {
  const params = new URLSearchParams()
  if (status) params.append('status', status)
  if (tier) params.append('tier', tier)
  if (exclude_layered) params.append('exclude_layered', 'true')
  if (study_type) params.append('study_type', study_type)
  if (additive_mol_id) params.append('additive_mol_id', additive_mol_id)
  if (temperature_min != null) params.append('temperature_min', temperature_min)
  if (temperature_max != null) params.append('temperature_max', temperature_max)
  if (additive_type) params.append('additive_type', additive_type)
  if (e_intra_method) params.append('e_intra_method', e_intra_method)
  params.append('limit', limit)

  const response = await api.get(`/experiments?${params}`)
  return response.data
}

export const getExperimentFilterOptions = async () => {
  const response = await api.get('/experiments/filter-options')
  return response.data
}

export const getExperiment = async (expId) => {
  const response = await api.get(`/experiments/${expId}`)
  return response.data
}

export const submitExperiment = async (data) => {
  const response = await api.post('/experiments', data)
  return response.data
}

export const getExportFormats = async () => {
  const response = await api.get('/experiments/export/formats')
  return response.data
}

export const exportExperiments = async ({
  format = 'csv',
  status,
  tier,
  study_type,
  additive_mol_id,
  e_intra_method,
  limit = 1000,
} = {}) => {
  const params = new URLSearchParams()
  params.append('format', format)
  if (status) params.append('status', status)
  if (tier) params.append('tier', tier)
  if (study_type) params.append('study_type', study_type)
  if (additive_mol_id) params.append('additive_mol_id', additive_mol_id)
  if (e_intra_method) params.append('e_intra_method', e_intra_method)
  params.append('limit', limit)

  const response = await api.get(`/experiments/export?${params}`, {
    responseType: 'blob',
  })

  // Create download link
  const extension = format === 'xlsx' ? 'xlsx' : 'csv'
  const mimeType = format === 'xlsx'
    ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    : 'text/csv'
  const blob = new Blob([response.data], { type: mimeType })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `experiments_${new Date().toISOString().slice(0, 10)}.${extension}`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)

  return { success: true }
}

export const deleteExperiment = async (expId) => {
  const response = await api.delete(`/experiments/${expId}`)
  return response.data
}

export const cancelExperiment = async (expId) => {
  const response = await api.post(`/experiments/${expId}/cancel`)
  return response.data
}

export const retryExperiment = async (expId) => {
  const response = await api.post(`/experiments/${expId}/retry`)
  return response.data
}

export const batchCancelExperiments = async (expIds) => {
  const response = await api.post('/experiments/batch/cancel', { exp_ids: expIds })
  return response.data
}

export const batchDeleteExperiments = async (expIds) => {
  const response = await api.post('/experiments/batch/delete', { exp_ids: expIds })
  return response.data
}

export const batchRetryExperiments = async (expIds) => {
  const response = await api.post('/experiments/batch/retry', { exp_ids: expIds })
  return response.data
}

export const getExperimentDefaults = async () => {
  const response = await api.get('/experiments/defaults')
  return response.data
}

export const submitSingleMoleculeBatch = async (payload) => {
  const response = await api.post('/experiments/single-molecule/batch', payload)
  return response.data
}
