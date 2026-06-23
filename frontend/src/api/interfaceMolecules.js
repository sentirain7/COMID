import api from './axiosInstance'

// Molecule catalog endpoints
export const listInterfaceMolecules = async () => {
  const response = await api.get('/interface-molecules')
  return response.data
}

export const getInterfaceMoleculePreview = async (molId) => {
  const response = await api.get(`/interface-molecules/${molId}/preview`)
  return response.data
}

// Cell library endpoints
export const listInterfaceMoleculeCells = async ({ status, limit = 100, visibility = 'library' } = {}) => {
  const params = new URLSearchParams()
  if (status) params.append('status', status)
  if (visibility) params.append('visibility', visibility)
  params.append('limit', String(limit))
  const response = await api.get(`/interface-molecule-cells?${params}`)
  return response.data
}

export const getInterfaceMoleculeCell = async (cellId) => {
  const response = await api.get(`/interface-molecule-cells/${cellId}`)
  return response.data
}

export const getInterfaceMoleculeCellPreview = async (cellId) => {
  const response = await api.get(`/interface-molecule-cells/${cellId}/preview`)
  return response.data
}

export const createInterfaceMoleculeCell = async (payload) => {
  const response = await api.post('/interface-molecule-cells', payload)
  return response.data
}

export const deleteInterfaceMoleculeCell = async (cellId) => {
  const response = await api.delete(`/interface-molecule-cells/${cellId}`)
  return response.data
}

/**
 * Get batch generation progress.
 * @param {string} batchId - The batch ID from async endpoint
 * @returns {Promise<{status: string, percent: number, items: object}>}
 */
export const getInterfaceBatchProgress = async (batchId) => {
  const response = await api.get(`/interface-molecule-cells/batch-progress/${batchId}`)
  return response.data
}

/**
 * Start async batch generation (non-blocking).
 * @param {object} payload - Batch generate request
 * @returns {Promise<{status: string, batch_id: string, poll_url: string}>}
 */
export const batchGenerateInterfaceMoleculeCellsAsync = async (payload) => {
  const response = await api.post('/interface-molecule-cells/batch-generate-async', payload)
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
 * @returns {Promise<{mol_id: string, mol_name: string, generated_count: number, skipped_count: number, failed_count: number, failures: array, cells: array}>}
 */
export const batchGenerateInterfaceMoleculeCells = async (payload, options = {}) => {
  const {
    pollIntervalMs = 1000,
    timeoutMs = 300000,
    onProgress = null
  } = options

  // Start async batch
  const startResponse = await batchGenerateInterfaceMoleculeCellsAsync(payload)
  const batchId = startResponse.batch_id

  // Poll for completion
  const startTime = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const progress = await getInterfaceBatchProgress(batchId)

    if (onProgress) {
      onProgress(progress)
    }

    // Check terminal states
    if (progress.status === 'completed' || progress.status === 'completed_with_errors') {
      // Codex fix: Transform to legacy response format matching InterfaceMoleculeBatchGenerateResponse
      // UI expects: {mol_id, mol_name, generated_count, skipped_count, failed_count, failures, cells: [InterfaceMoleculeCellResponse]}
      const items = progress.items || {}
      const metadata = progress.metadata || {}

      // Extract full response objects from items (stored by service.py)
      // Filter out failed items, only include completed/skipped with full response
      const cells = Object.values(items)
        .filter(info => info.status !== 'failed' && info.result && info.result.cell_id)
        .map(info => info.result)

      // Extract failures with error info
      // Codex fix: Restore legacy BatchFailureItem shape for UI compatibility
      // UI reads failures[0].message, so we must include it
      const failures = Object.entries(items)
        .filter(([, info]) => info.status === 'failed')
        .map(([size, info]) => {
          const errorMsg = info.result?.error || 'Unknown error'
          // Parse size label (e.g., "50x50") to reconstruct dimensions
          const parts = size.split('x').map(Number)
          const lx = parts[0] || 0
          const ly = parts[1] || parts[0] || 0
          return {
            // BatchFailureItem schema fields (UI expects these)
            lx_angstrom: lx,
            ly_angstrom: ly,
            lz_angstrom: payload.lz_angstrom || 0,
            error_code: 'BATCH_GENERATION_FAILED',
            message: errorMsg,
            // Legacy fields for backward compatibility
            size,
            error: errorMsg
          }
        })

      return {
        mol_id: metadata.mol_id || payload.mol_id,
        mol_name: metadata.mol_name || payload.mol_id,
        generated_count: progress.completed || 0,
        skipped_count: progress.skipped || 0,
        failed_count: progress.failed || 0,
        failures,
        cells
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
