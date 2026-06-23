import api from './axiosInstance'

export const listMolecules = async ({
  saraType,
  agingState,
  temperatureCode,
  limit = 100,
  offset = 0,
  // PR 2 (Method 1a SSOT, Codex Round 6): pass through the optional
  // ``e_intra_method`` query param so the UI can request a specific method's
  // coverage view.  Default (undefined) → Method 1 baseline on the server.
  eIntraMethod,
} = {}) => {
  const params = new URLSearchParams()
  if (saraType) params.append('sara_type', saraType)
  if (agingState) params.append('aging_state', agingState)
  if (temperatureCode) params.append('temperature_code', temperatureCode)
  params.append('limit', limit)
  params.append('offset', offset)
  if (eIntraMethod) params.append('e_intra_method', eIntraMethod)

  const response = await api.get(`/molecules?${params}`)
  return response.data
}

export const getEIntra = async (
  molId,
  ffName = 'GAFF2',
  ffVersion = '2.11',
  // PR 2 (Codex Round 6): optional method override for detail fetches.
  eIntraMethod,
) => {
  const params = new URLSearchParams({
    ff_name: ffName,
    ff_version: ffVersion,
  })
  if (eIntraMethod) params.append('e_intra_method', eIntraMethod)
  const response = await api.get(`/e_intra/${molId}?${params}`)
  return response.data
}

export const getMoleculeStructure = async (molId, signal) => {
  // encodeURIComponent for parity with the other artifact endpoints below.
  // Also apply a per-request 30s timeout — the backend's observe_only
  // preview path is fast (<100ms), but any network or server regression
  // should surface as an AbortError in the UI instead of an infinite spinner.
  const response = await api.get(
    `/molecules/${encodeURIComponent(molId)}/structure`,
    { signal, timeout: 30_000 },
  )
  return response.data
}

// ---------------------------------------------------------------------------
// Artifact deletion (public)
//
// Public generate/status/batch endpoints remain available on the backend for
// legacy/operator clients (see backend /artifacts/* routes + topology_helpers
// error messages), but the frontend no longer calls them — admin variants
// under /artifacts/admin/* are the canonical client path (v00.99.66).
// ---------------------------------------------------------------------------

export async function deleteArtifact(molId, { force = false } = {}) {
  const params = force ? '?force=true' : ''
  const { data } = await api.delete(`/artifacts/${encodeURIComponent(molId)}${params}`)
  return data
}

export async function deleteEIntra(molId, { eIntraMethod, allMethods = false } = {}) {
  // PR 2 (Codex Round 6): the backend now requires an explicit choice
  // between method-scoped delete (``e_intra_method``) and the legacy
  // delete-all (``all_methods=true``).  Default to Method 1 baseline when
  // neither is provided to preserve the typical single-method UX without
  // accidentally wiping a coexisting Method 1a row.
  const params = new URLSearchParams()
  if (allMethods) {
    params.append('all_methods', 'true')
  } else {
    params.append('e_intra_method', eIntraMethod || 'single_molecule_vacuum')
  }
  const { data } = await api.delete(
    `/e_intra/${encodeURIComponent(molId)}?${params.toString()}`,
  )
  return data
}

// ---------------------------------------------------------------------------
// Admin FF artifact control plane (v00.99.41). All admin endpoints are gated
// on the backend by ASPHALT_ANTECHAMBER_ADMIN. The capabilities probe client
// was removed in v00.99.66 (admin gate is no longer surfaced in the UI;
// /molecules is the canonical FF surface). The /artifacts/admin/capabilities
// backend route remains available for operator/diagnostic clients.
// ---------------------------------------------------------------------------

export async function getAdminArtifactStatus() {
  const { data } = await api.get('/artifacts/admin/status')
  return data
}

export async function adminGenerateArtifact(molId, profile = 'baseline') {
  const params = new URLSearchParams({ profile })
  const { data } = await api.post(
    `/artifacts/admin/generate/${encodeURIComponent(molId)}?${params}`,
  )
  return data
}

export async function adminDiagnoseArtifact(molId) {
  const { data } = await api.post(
    `/artifacts/admin/diagnose/${encodeURIComponent(molId)}`,
  )
  return data
}

// v00.99.43 — Admin batch operations.
export async function getAdminBatchProgress() {
  const { data } = await api.get('/artifacts/admin/batch-progress')
  return data
}

export async function adminGenerateAll(profile = 'baseline', force = false) {
  const params = new URLSearchParams({ profile, ...(force && { force: 'true' }) })
  const { data } = await api.post(`/artifacts/admin/generate-all?${params}`)
  return data
}

export async function adminGenerateSelected(molIds, profile = 'baseline', force = false) {
  const { data } = await api.post('/artifacts/admin/generate-selected', {
    mol_ids: molIds,
    profile,
    force,
  })
  return data
}

export async function adminCancelBatch(force = false) {
  // Reuses the public cancel endpoint — only one batch can run at a
  // time so the same cancel signal applies to admin and public batches.
  // force=true removes all lock files and resets batch state immediately.
  const params = force ? '?force=true' : ''
  const { data } = await api.post(`/artifacts/cancel-batch${params}`)
  return data
}

export async function adminResetBatch() {
  // Force-reset a stuck batch slot (running=true after abnormal termination
  // or when graceful cancel takes too long).
  const { data } = await api.post('/artifacts/admin/reset-batch')
  return data
}
