/**
 * URL drift regression test for api/molecules.js artifact endpoints.
 *
 * The backend router (src/features/molecules/router.py) exposes artifact
 * endpoints under /artifacts/... without a /molecules prefix. This test
 * pins each artifact function to its canonical path so the drift cannot
 * reappear.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('../axiosInstance', () => {
  const api = {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
  }
  return { default: api }
})

import api from '../axiosInstance'
import {
  adminCancelBatch,
  adminDiagnoseArtifact,
  adminGenerateAll,
  adminGenerateArtifact,
  adminGenerateSelected,
  deleteArtifact,
  deleteEIntra,
  getAdminArtifactStatus,
  getAdminBatchProgress,
} from '../molecules'

beforeEach(() => {
  api.get.mockClear()
  api.post.mockClear()
  api.delete.mockClear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('api/molecules artifact endpoint URLs', () => {
  test('deleteArtifact calls DELETE /artifacts/{mol_id} (not /molecules/artifacts/...)', async () => {
    await deleteArtifact('CNT')
    expect(api.delete).toHaveBeenCalledWith('/artifacts/CNT')
    expect(api.delete).not.toHaveBeenCalledWith('/molecules/artifacts/CNT')
  })

  test('deleteArtifact URL-encodes mol_id with special characters', async () => {
    await deleteArtifact('U-AS-Thio-0293')
    expect(api.delete).toHaveBeenCalledWith('/artifacts/U-AS-Thio-0293')
  })

  test('deleteEIntra defaults to method-scoped DELETE /e_intra/{mol_id}?e_intra_method=single_molecule_vacuum', async () => {
    await deleteEIntra('U-AS-Thio-0293')
    expect(api.delete).toHaveBeenCalledWith(
      '/e_intra/U-AS-Thio-0293?e_intra_method=single_molecule_vacuum',
    )
  })

  test('deleteEIntra forwards an explicit method override', async () => {
    await deleteEIntra('U-AS-Thio-0293', {
      eIntraMethod: 'single_molecule_vacuum_adaptive_cutoff',
    })
    expect(api.delete).toHaveBeenCalledWith(
      '/e_intra/U-AS-Thio-0293?e_intra_method=single_molecule_vacuum_adaptive_cutoff',
    )
  })

  test('deleteEIntra supports delete-all mode', async () => {
    await deleteEIntra('U-AS-Thio-0293', { allMethods: true })
    expect(api.delete).toHaveBeenCalledWith(
      '/e_intra/U-AS-Thio-0293?all_methods=true',
    )
  })

  // v00.99.43 — admin endpoints. Admin is the canonical client path after
  // v00.99.66 removed ArtifactPanel (submit screens no longer call
  // public /artifacts/* routes; those remain server-side for legacy /
  // operator clients only). getAdminCapabilities was also dropped since
  // the admin gate UI was already removed in v00.99.45.
  test('getAdminArtifactStatus calls GET /artifacts/admin/status', async () => {
    await getAdminArtifactStatus()
    expect(api.get).toHaveBeenCalledWith('/artifacts/admin/status')
  })

  test('getAdminBatchProgress calls GET /artifacts/admin/batch-progress', async () => {
    await getAdminBatchProgress()
    expect(api.get).toHaveBeenCalledWith('/artifacts/admin/batch-progress')
  })

  test('adminGenerateArtifact calls POST /artifacts/admin/generate/{mol_id} with profile', async () => {
    await adminGenerateArtifact('U-AS-Thio-0293', 'sqm_robust')
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/admin/generate/U-AS-Thio-0293?profile=sqm_robust',
    )
  })

  test('adminGenerateArtifact defaults profile to baseline', async () => {
    await adminGenerateArtifact('U-AS-Thio-0293')
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/admin/generate/U-AS-Thio-0293?profile=baseline',
    )
  })

  test('adminDiagnoseArtifact calls POST /artifacts/admin/diagnose/{mol_id}', async () => {
    await adminDiagnoseArtifact('CNT')
    expect(api.post).toHaveBeenCalledWith('/artifacts/admin/diagnose/CNT')
  })

  test('adminGenerateAll calls POST /artifacts/admin/generate-all with profile query', async () => {
    await adminGenerateAll('sqm_robust')
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/admin/generate-all?profile=sqm_robust',
    )
  })

  test('adminGenerateAll defaults profile to baseline', async () => {
    await adminGenerateAll()
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/admin/generate-all?profile=baseline',
    )
  })

  test('adminGenerateAll appends force=true when requested', async () => {
    await adminGenerateAll('baseline', true)
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/admin/generate-all?profile=baseline&force=true',
    )
  })

  test('adminGenerateSelected posts mol_ids, profile, force in body', async () => {
    await adminGenerateSelected(['A', 'B'], 'sqm_robust', true)
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/admin/generate-selected',
      { mol_ids: ['A', 'B'], profile: 'sqm_robust', force: true },
    )
  })

  test('adminGenerateSelected defaults profile=baseline and force=false', async () => {
    await adminGenerateSelected(['A'])
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/admin/generate-selected',
      { mol_ids: ['A'], profile: 'baseline', force: false },
    )
  })

  test('adminCancelBatch reuses the public cancel endpoint', async () => {
    await adminCancelBatch()
    expect(api.post).toHaveBeenCalledWith('/artifacts/cancel-batch')
  })
})
