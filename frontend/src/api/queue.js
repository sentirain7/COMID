import api from './axiosInstance'

export const getQueueStats = async () => {
  const response = await api.get('/queue/stats')
  return response.data
}
