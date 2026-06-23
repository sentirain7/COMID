import api from './axiosInstance'

export const listBinderStudies = async (state) => {
  const params = new URLSearchParams()
  if (state) params.append('state', state)
  const suffix = params.toString()
  const { data } = await api.get(`/analysis/binder-studies${suffix ? `?${suffix}` : ''}`)
  return data
}

export const getBinderStudy = async (studyId) => {
  const { data } = await api.get(`/analysis/binder-studies/${studyId}`)
  return data
}

export const getBinderStudyResults = async (studyId) => {
  const { data } = await api.get(`/analysis/binder-studies/${studyId}/results`)
  return data
}

export const deleteBinderStudy = async (studyId) => {
  const { data } = await api.delete(`/analysis/binder-studies/${studyId}`)
  return data
}
