import api from './axiosInstance'

export const listJobs = async ({ status, limit = 100 } = {}) => {
  const params = new URLSearchParams()
  if (status) params.append('status', status)
  params.append('limit', limit)
  const response = await api.get(`/jobs?${params}`)
  return response.data
}

export const getJob = async (jobId) => {
  const response = await api.get(`/jobs/${jobId}`)
  return response.data
}

export const cancelJob = async (jobId) => {
  const response = await api.delete(`/jobs/${jobId}`)
  return response.data
}

export const deleteJob = async (jobId) => {
  const response = await api.delete(`/jobs/${jobId}?action=delete`)
  return response.data
}

export const retryJob = async (jobId) => {
  const response = await api.post(`/jobs/${jobId}/retry`)
  return response.data
}

export const cleanupOldJobs = async (olderThanHours = 24) => {
  const response = await api.post(`/jobs/cleanup?older_than_hours=${olderThanHours}`)
  return response.data
}

export const deleteAllCompletedJobs = async () => {
  const response = await api.delete('/jobs/completed')
  return response.data
}
