import api from './axiosInstance'

// Inverse-design pipeline (P3 backend: /inverse-design/*)
// stateless design: the plan document is not stored on the server, and on approval the
// plan/plan_hash are sent back as-is for the server to re-validate.

export const previewInversePlan = async (body) => {
  const { data } = await api.post('/inverse-design/plan', body)
  return data
}

export const approveInversePlan = async ({ plan, plan_hash }) => {
  const { data } = await api.post('/inverse-design/plan/approve', { plan, plan_hash })
  return data
}

export const getInversePipelineProgress = async (pipelineId) => {
  const { data } = await api.get(`/inverse-design/${pipelineId}/progress`)
  return data
}

export const getInversePipelineResults = async (pipelineId) => {
  const { data } = await api.get(`/inverse-design/${pipelineId}/results`)
  return data
}
