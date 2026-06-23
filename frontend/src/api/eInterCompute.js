/**
 * E_inter Compute API — CPU rerun precision analysis endpoints
 */
import api from './axiosInstance'

/**
 * Get E_inter precision analysis recommendation.
 *
 * @param {Object} params
 * @param {string} params.workflow - Workflow type (batch_binder_cell, layered_structure, etc.)
 * @param {string} [params.tier] - Run tier (screening, confirm, viscosity)
 * @param {number} [params.layer_count] - Number of layers (for layered structures)
 * @param {boolean} [params.has_additive] - Whether additives are included
 * @param {boolean} [params.has_water_ion] - Whether water/ion molecules are included
 * @param {number} [params.estimated_atoms] - Estimated atom count
 * @returns {Promise<Object>} Recommendation response
 */
export async function getEInterRecommendation(params) {
  const { data } = await api.post('/e-inter/recommendation', params)
  return data
}

/**
 * Create a CPU rerun job for a completed experiment.
 *
 * @param {string} expId - Experiment ID
 * @param {Object} [options]
 * @param {string[]} [options.metrics] - Metrics to compute (default: ['e_inter_total'])
 * @returns {Promise<Object>} Job creation response
 */
export async function createCpuRerunJob(expId, options = {}) {
  // Codex #3: send metrics as JSON body, not query params
  // Codex #2: normalize empty metrics to default
  const metrics = options.metrics?.length ? options.metrics : ['e_inter_total']
  const { data } = await api.post(`/e-inter/jobs/${expId}`, { metrics })
  return data
}

/**
 * Get CPU rerun job status for an experiment.
 *
 * @param {string} expId - Experiment ID
 * @returns {Promise<Object>} Job status response
 */
export async function getCpuRerunJobStatus(expId) {
  const { data } = await api.get(`/e-inter/jobs/${expId}`)
  return data
}
