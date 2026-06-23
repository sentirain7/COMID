import api from './axiosInstance'

export const listCrystalStructures = async ({ status, limit = 100, visibility = 'library' } = {}) => {
  const params = new URLSearchParams()
  if (status) params.append('status', status)
  if (visibility) params.append('visibility', visibility)
  params.append('limit', String(limit))
  const response = await api.get(`/crystal-structures?${params}`)
  return response.data
}

export const getCrystalStructure = async (crystalId) => {
  const response = await api.get(`/crystal-structures/${crystalId}`)
  return response.data
}

export const getCrystalStructurePreview = async (crystalId) => {
  const response = await api.get(`/crystal-structures/${crystalId}/preview`)
  return response.data
}

export const createCrystalStructure = async (payload) => {
  const response = await api.post('/crystal-structures', payload)
  return response.data
}

export const deleteCrystalStructure = async (crystalId) => {
  const response = await api.delete(`/crystal-structures/${crystalId}`)
  return response.data
}

/**
 * Get batch generation progress.
 * @param {string} batchId - The batch ID from async endpoint
 * @returns {Promise<{status: string, percent: number, items: object}>}
 */
export const getCrystalBatchProgress = async (batchId) => {
  const response = await api.get(`/crystal-structures/batch-progress/${batchId}`)
  return response.data
}

/**
 * Start async batch generation (non-blocking).
 * @param {object} payload - Batch generate request
 * @returns {Promise<{status: string, batch_id: string, poll_url: string}>}
 */
export const batchGenerateCrystalSizesAsync = async (payload) => {
  const response = await api.post('/crystal-structures/batch-generate-async', payload)
  return response.data
}

/**
 * Batch generate with polling (waits for completion).
 * Codex fix: Use async endpoint instead of deprecated sync endpoint.
 * Returns legacy response shape for backward compatibility with UI.
 *
 * @param {object} payload - Batch generate request
 * @param {object} [options] - Options
 * @param {number} [options.pollIntervalMs=1000] - Polling interval
 * @param {number} [options.timeoutMs=300000] - Timeout (5 minutes default)
 * @param {function} [options.onProgress] - Progress callback
 * @returns {Promise<{material: string, surface: string, generated_count: number, skipped_count: number, sizes: array}>}
 */
export const batchGenerateCrystalSizes = async (payload, options = {}) => {
  const {
    pollIntervalMs = 1000,
    timeoutMs = 300000,
    onProgress = null
  } = options

  // Start async batch
  const startResponse = await batchGenerateCrystalSizesAsync(payload)
  const batchId = startResponse.batch_id

  // Poll for completion
  const startTime = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const progress = await getCrystalBatchProgress(batchId)

    if (onProgress) {
      onProgress(progress)
    }

    // Check terminal states
    if (progress.status === 'completed' || progress.status === 'completed_with_errors') {
      // Codex fix: Transform to legacy response format matching CrystalBatchGenerateResponse
      // UI expects: {material, surface, generated_count, skipped_count, sizes: [CrystalStructureResponse]}
      const items = progress.items || {}
      const metadata = progress.metadata || {}

      // Extract full response objects from items (stored by service.py)
      // Filter out failed items, only include completed/skipped with full response
      const sizes = Object.values(items)
        .filter(info => info.status !== 'failed' && info.result && info.result.crystal_id)
        .map(info => info.result)

      return {
        material: metadata.material || payload.material,
        surface: metadata.surface || null,
        generated_count: progress.completed || 0,
        skipped_count: progress.skipped || 0,
        sizes
      }
    }

    if (progress.status === 'failed') {
      throw new Error(progress.error || 'Batch generation failed')
    }

    if (progress.status === 'not_found') {
      throw new Error('Batch not found')
    }

    // Check timeout
    if (Date.now() - startTime > timeoutMs) {
      throw new Error('Batch generation timed out')
    }

    // Wait before next poll
    await new Promise(resolve => setTimeout(resolve, pollIntervalMs))
  }
}
