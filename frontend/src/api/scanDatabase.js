import api from './axiosInstance'

export const scanDatabase = async () => {
  const { data } = await api.post('/scan-database/scan')
  return data
}

export const importExperiments = async (params) => {
  const { data } = await api.post('/scan-database/import', params)
  return data
}

export const deleteScannedExperiments = async (params) => {
  const { data } = await api.post('/scan-database/delete', params)
  return data
}
