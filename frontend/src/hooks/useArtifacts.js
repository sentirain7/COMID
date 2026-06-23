import { useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { deleteArtifact, deleteEIntra, getAdminArtifactStatus, adminGenerateArtifact, adminDiagnoseArtifact, getAdminBatchProgress, adminGenerateAll, adminGenerateSelected, adminCancelBatch, adminResetBatch } from '../api/client'

// v00.99.43: admin mutation invalidation policy.
// Every admin mutation that may have changed the catalog or sidecar must
// invalidate ALL four caches so the FF Parameters page, the public
// artifact status, and the public Molecules page (which reads
// ['molecules']) all refetch in lockstep. Using a single helper keeps
// the policy in one place — Codex's audit caught us missing
// ['molecules'] previously.
const _ADMIN_INVALIDATION_KEYS = [
  ['artifact-admin-status'],
  ['artifact-admin-batch-progress'],
  ['artifact-status'],
  ['molecules'],
]

function _invalidateAdminCaches(qc) {
  for (const key of _ADMIN_INVALIDATION_KEYS) {
    qc.invalidateQueries({ queryKey: key })
  }
}

export function useDeleteArtifact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ molId, force = false }) => deleteArtifact(molId, { force }),
    onSuccess: () => _invalidateAdminCaches(qc),
  })
}

export function useDeleteEIntra() {
  // PR 2 (Codex Round 7): accept either a bare ``molId`` (legacy callers,
  // baseline-scoped delete) or the structured form ``{ molId, eIntraMethod,
  // allMethods }`` so the UI can choose between method-scoped and
  // delete-all-methods semantics.
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (arg) => {
      if (typeof arg === 'string') {
        return deleteEIntra(arg)
      }
      const { molId, eIntraMethod, allMethods } = arg || {}
      return deleteEIntra(molId, { eIntraMethod, allMethods })
    },
    onSuccess: () => _invalidateAdminCaches(qc),
  })
}

// ---------------------------------------------------------------------------
// Admin FF artifact control plane (v00.99.41, gated by backend
// ASPHALT_ANTECHAMBER_ADMIN env var). Admin gate was removed from the UI in
// v00.99.45 so the capabilities probe hook was dropped in v00.99.66 — query
// keys stay namespaced under 'artifact-admin-*' to avoid collision with
// ['artifact-status'] / ['artifact-batch-progress'] if those routes return.
// ---------------------------------------------------------------------------

export function useAdminArtifactStatus(enabled = true) {
  return useQuery({
    queryKey: ['artifact-admin-status'],
    queryFn: getAdminArtifactStatus,
    enabled,
    refetchInterval: false,
  })
}

export function useAdminGenerateArtifact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ molId, profile = 'baseline' }) =>
      adminGenerateArtifact(molId, profile),
    // 4-key invalidation: admin status, admin batch-progress (in case a
    // batch was running), public status, AND ['molecules'] so the public
    // Molecules page refetches without a manual reload.
    onSuccess: () => _invalidateAdminCaches(qc),
  })
}

export function useAdminDiagnoseArtifact() {
  // Diagnose is read-only — the modal renders the returned payload via
  // page-local state. No cache invalidation needed.
  return useMutation({
    mutationFn: (molId) => adminDiagnoseArtifact(molId),
  })
}

// v00.99.43 — admin batch operations.

export function useAdminBatchProgress(enabled = false) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['artifact-admin-batch-progress'],
    queryFn: getAdminBatchProgress,
    enabled,
    // Poll only when a batch is actually running to avoid overloading
    // the API server. Initial fetch always runs (via enabled=true).
    refetchInterval: (query) =>
      query.state.data?.running ? 3000 : false,
  })

  // v00.99.55: detect running true→false transition (batch just finished)
  // and invalidate downstream caches so FF badges, molecule catalog, and
  // sidecar-driven surfaces all refresh without waiting for another
  // admin mutation or manual reload.
  //
  // v00.99.56: also refresh on every polling tick that reports a newly
  // completed or failed mol so the FF badge / E_intra / Preview surfaces
  // reflect partial progress without waiting for the whole batch to finish.
  // Partial ticks skip ['artifact-status'] (public) and ['molecules', 'totals']
  // (category aggregates unchanged during a batch) to avoid overfetching.
  const prevRunning = useRef(false)
  const prevCompleted = useRef(0)
  const prevFailed = useRef(0)
  useEffect(() => {
    const cur = Boolean(query.data?.running)
    const completed = Number(query.data?.completed) || 0
    const failed = Number(query.data?.failed) || 0

    if (prevRunning.current && !cur) {
      qc.invalidateQueries({ queryKey: ['artifact-admin-status'] })
      qc.invalidateQueries({ queryKey: ['artifact-status'] })
      qc.invalidateQueries({ queryKey: ['molecules'] })
    } else if (
      cur &&
      (completed > prevCompleted.current || failed > prevFailed.current)
    ) {
      qc.invalidateQueries({ queryKey: ['artifact-admin-status'] })
      qc.invalidateQueries({
        queryKey: ['molecules'],
        predicate: (q) => q.queryKey[1] !== 'totals',
      })
    }

    prevRunning.current = cur
    prevCompleted.current = completed
    prevFailed.current = failed
  }, [query.data?.running, query.data?.completed, query.data?.failed, qc])

  return query
}

export function useAdminGenerateAll() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (arg = {}) => {
      const profile = typeof arg === 'string' ? arg : (arg?.profile || 'baseline')
      const force = typeof arg === 'object' ? Boolean(arg?.force) : false
      return adminGenerateAll(profile, force)
    },
    // Invalidate immediately so UI reflects "generating" state
    onMutate: () => _invalidateAdminCaches(qc),
    onSuccess: () => _invalidateAdminCaches(qc),
  })
}

export function useAdminGenerateSelected() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ molIds, profile = 'baseline', force = false }) =>
      adminGenerateSelected(molIds, profile, force),
    onMutate: () => _invalidateAdminCaches(qc),
    onSuccess: () => _invalidateAdminCaches(qc),
  })
}

export function useAdminCancelBatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ force = false } = {}) => adminCancelBatch(force),
    onSuccess: () => _invalidateAdminCaches(qc),
  })
}

export function useAdminResetBatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: adminResetBatch,
    onSuccess: () => _invalidateAdminCaches(qc),
  })
}
