import api from './axiosInstance'

export const getSettings = async () => {
  const response = await api.get('/settings')
  return response.data
}

export const updateSettings = async (settings) => {
  const response = await api.put('/settings', settings)
  return response.data
}
