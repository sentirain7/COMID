import api from './axiosInstance'

export const getAnalysisEmbedding = async (ffType = 'bulk_ff_gaff2') => {
  const response = await api.get(`/analysis/embedding?ff_type=${ffType}`)
  return response.data
}

export const getAnalysisMoleculeImpact = async (ffType = 'bulk_ff_gaff2') => {
  const response = await api.get(`/analysis/molecule-impact?ff_type=${ffType}`)
  return response.data
}

export const getBinderCellXYSummary = async (groupBy = 'binder', ffType = 'bulk_ff_gaff2') => {
  const params = new URLSearchParams()
  params.append('group_by', groupBy)
  params.append('ff_type', ffType)
  const response = await api.get(`/analysis/binder-cells/xy-summary?${params}`)
  return response.data
}

export const getScatter3D = async (axisX, axisY, axisZ, ffType = 'bulk_ff_gaff2') => {
  const response = await api.get('/analysis/scatter3d', {
    params: { axis_x: axisX, axis_y: axisY, axis_z: axisZ, ff_type: ffType },
  })
  return response.data
}
