import api from './axiosInstance'

export const getDefaultStages = async (tier = 'screening', { includeOptional = false } = {}) => {
  const params = new URLSearchParams()
  if (includeOptional) params.append('include_optional', 'true')
  const suffix = params.size ? `?${params}` : ''
  const response = await api.get(`/protocol/default-stages/${tier}${suffix}`)
  return response.data
}
