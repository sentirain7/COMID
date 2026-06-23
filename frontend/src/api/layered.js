import api from './axiosInstance'

export const listLayerSources = async (sourceType, { limit = 100, visibility = 'library' } = {}) => {
  const params = new URLSearchParams()
  params.append('limit', String(limit))
  if (visibility) params.append('visibility', visibility)
  const response = await api.get(`/layered-structures/sources/${sourceType}?${params}`)
  return response.data
}

export const previewLayeredStructure = async (payload) => {
  const response = await api.post('/layered-structures/preview', payload)
  return response.data
}

export const submitLayeredStructure = async (payload) => {
  const response = await api.post('/layered-structures/submit', payload)
  return response.data
}

export const listLayeredExperiments = async ({ status, limit = 200 } = {}) => {
  const params = new URLSearchParams()
  if (status) params.append('status', status)
  params.append('limit', String(limit))
  const response = await api.get(`/layered-structures?${params}`)
  return response.data
}

export const getStressStrainCurve = async (expId) => {
  const response = await api.get(`/experiments/${expId}/stress-strain`)
  return response.data
}

export const getLayeredAnalysis3D = async (params = {}) => {
  const qs = new URLSearchParams()
  if (params.layer_types?.length) params.layer_types.forEach((v) => qs.append('layer_types', v))
  if (params.crystal_materials?.length) params.crystal_materials.forEach((v) => qs.append('crystal_materials', v))
  if (params.aging_states?.length) params.aging_states.forEach((v) => qs.append('aging_states', v))
  if (params.temp_min != null) qs.append('temp_min', String(params.temp_min))
  if (params.temp_max != null) qs.append('temp_max', String(params.temp_max))
  qs.append('limit', String(params.limit || 500))
  const response = await api.get(`/layered-structures/analysis/3d?${qs}`)
  return response.data
}
