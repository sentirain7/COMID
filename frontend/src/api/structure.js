import api from './axiosInstance'

export const getStructureXYZ = async (expId, stage) => {
  const response = await api.get(`/experiments/${expId}/structure/${stage}`)
  return response.data
}

export const getAvailableStages = async (expId) => {
  const response = await api.get(`/experiments/${expId}/available-stages`)
  return response.data
}
