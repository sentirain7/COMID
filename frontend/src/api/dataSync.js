import api from './axiosInstance'

export const scanAssets = async (assetType) => {
  const res = await api.post('/data-sync/scan', { asset_type: assetType })
  return res.data
}

export const importAssets = async ({ asset_type, asset_ids, force_import = false }) => {
  const res = await api.post('/data-sync/import', { asset_type, asset_ids, force_import })
  return res.data
}

export const backupToNas = async (assetTypes = ['all']) => {
  const res = await api.post('/data-sync/backup', { asset_types: assetTypes })
  return res.data
}

export const loadFromNas = async (manifestPath = null) => {
  const res = await api.post('/data-sync/load', { manifest_path: manifestPath })
  return res.data
}

export const applyNasLoad = async ({ manifest_path, targets = null }) => {
  const res = await api.post('/data-sync/apply', { manifest_path, targets })
  return res.data
}

export const getNasStatus = async () => {
  const res = await api.get('/data-sync/nas-status')
  return res.data
}
