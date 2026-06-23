import api from './axiosInstance'

export const getGPUStats = async () => {
  const response = await api.get('/resources/gpus')
  return response.data
}

export const getRunningJobs = async () => {
  const response = await api.get('/jobs/running')
  return response.data
}

export const getSystemStats = async () => {
  const response = await api.get('/system/stats')
  return response.data
}
