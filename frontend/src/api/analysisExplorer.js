/**
 * Analysis Explorer API client functions.
 */
import api from './axiosInstance'

export const getExplorerCatalog = async () => {
  const response = await api.get('/analysis/explorer/catalog')
  return response.data
}

export const postExplorerData = async (request) => {
  const response = await api.post('/analysis/explorer/data', request)
  return response.data
}

export const postExplorerAggregate = async (request) => {
  const response = await api.post('/analysis/explorer/aggregate', request)
  return response.data
}
