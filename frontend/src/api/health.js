import api from './axiosInstance'

export const getHealth = async () => {
  const response = await api.get('/health')
  return response.data
}

export const getRecoveryCheck = async () => {
  const response = await api.get('/recovery/check')
  return response.data
}

export const getRecoveryCandidates = async () => {
  const response = await api.get('/recovery/candidates')
  return response.data
}

export const executeRecoveryAction = async ({ exp_id, action }) => {
  const response = await api.post('/recovery/execute', { exp_id, action })
  return response.data
}

export const executeAllRecoveryActions = async () => {
  const response = await api.post('/recovery/execute-all')
  return response.data
}
