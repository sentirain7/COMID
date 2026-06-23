import api from './axiosInstance'

export const validateBatchJobBinderCell = async (payload) => {
  const response = await api.post('/batch-job/binder-cell/validate', payload)
  return response.data
}

export const createBatchJobBinderCell = async (payload) => {
  const response = await api.post('/batch-job/binder-cell', payload)
  return response.data
}
