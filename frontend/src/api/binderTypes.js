import api from './axiosInstance'

export const listBinderTypes = async () => {
  const response = await api.get('/binder-types')
  return response.data
}

export const getBinderComposition = async (binderType, size = 'X1', aging = 'non_aging', tempCode = '0293') => {
  const params = new URLSearchParams({
    size,
    aging,
    temp_code: tempCode,
  })
  const response = await api.get(`/binder-types/${binderType}/composition?${params}`)
  return response.data
}

export const listAdditives = async () => {
  const response = await api.get('/additives')
  return response.data
}

export const submitMoleculeExperiment = async (data) => {
  const response = await api.post('/experiments/molecule-based', data)
  return response.data
}

export const previewMoleculeComposition = async (data) => {
  const response = await api.post('/experiments/molecule-based/preview', data)
  return response.data
}

/**
 * @deprecated Use checkTypingReadiness() or prepareTypingCharge() instead.
 * This endpoint is kept for legacy script compatibility.
 * DO NOT call from submit/validate frontend paths.
 */
export const precomputeTypingChargeCache = async (data) => {
  const response = await api.post('/experiments/molecule-based/precompute-typing-charge', data)
  return response.data
}

/**
 * Check typing/charge readiness for molecules (observe-only).
 * Does NOT trigger artifact generation. Returns readiness status instantly.
 * Use this in submit/validate paths before allowing submission.
 *
 * @param {Object} data - Request payload with molecule_counts, ff_type, etc.
 * @returns {Promise<Object>} Response with cached/failed counts and details
 */
export const checkTypingReadiness = async (data) => {
  const response = await api.post('/experiments/molecule-based/check-typing-readiness', data)
  return response.data
}

/**
 * Start background artifact preparation for molecules.
 * Returns 202 Accepted immediately. Poll /artifacts/batch-progress for status.
 * Use this when user explicitly requests artifact generation.
 *
 * @param {Object} data - Request payload with molecule_counts, ff_type, etc.
 * @returns {Promise<Object>} Response with status: 'accepted' and batch_kind
 */
export const prepareTypingCharge = async (data) => {
  const response = await api.post('/experiments/molecule-based/prepare-typing-charge', data)
  return response.data
}
