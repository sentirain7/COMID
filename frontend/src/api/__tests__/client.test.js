/**
 * Export parity test for api/client barrel.
 *
 * Ensures every named export that existed in the original monolithic client.js
 * is still re-exported after the domain-module split. Any removal or typo will
 * cause this test to fail.
 */
import * as client from '../client'

// Alphabetical list of named exports from the client barrel. v00.99.66 removed
// 7 public artifact generate/status/batch functions alongside ArtifactPanel
// retirement (getArtifactStatus, generateArtifact, generateAllArtifacts,
// getBatchProgress, cancelBatch, generateIonicArtifact, generateAllIonicArtifacts).
// Public generate/status/batch routes remain on the backend for legacy /
// operator clients — see src/features/molecules/router.py.
const EXPECTED_NAMED_EXPORTS = [
  'adminCancelBatch',
  'adminDiagnoseArtifact',
  'adminGenerateAll',
  'adminGenerateArtifact',
  'adminGenerateSelected',
  'adminResetBatch',
  'approveInversePlan',
  'batchCancelExperiments',
  'batchDeleteExperiments',
  'batchGenerateCrystalSizes',
  'batchGenerateCrystalSizesAsync',
  'batchGenerateInterfaceMoleculeCells',
  'batchGenerateInterfaceMoleculeCellsAsync',
  'batchRetryExperiments',
  'cancelExperiment',
  'cancelJob',
  'checkModelDrift',
  'checkTypingReadiness',
  'cleanupOldJobs',
  'createBatchJobBinderCell',
  'createCpuRerunJob',
  'createCrystalStructure',
  'createInterfaceMoleculeCell',
  'deleteAllCompletedJobs',
  'deleteArtifact',
  'deleteBinderStudy',
  'deleteCrystalStructure',
  'deleteEIntra',
  'deleteExperiment',
  'deleteInterfaceMoleculeCell',
  'deleteJob',
  'deleteScannedExperiments',
  'executeAllRecoveryActions',
  'executeRecoveryAction',
  'exportExperiments',
  'getAdminArtifactStatus',
  'getAdminBatchProgress',
  'getAnalysisEmbedding',
  'getAnalysisMoleculeImpact',
  'getArrayMetricCompare',
  'getArrayMetricData',
  'getAvailableStages',
  'getBinderCellXYSummary',
  'getBinderComposition',
  'getBinderStudy',
  'getBinderStudyResults',
  'getCEDByAdditive',
  'getChampionModel',
  'getCpuRerunJobStatus',
  'getCrystalBatchProgress',
  'getCrystalStructure',
  'getCrystalStructurePreview',
  'getDataCoverage',
  'getDataQuality',
  'getDefaultStages',
  'getDensityTemperatureData',
  'getEInterRecommendation',
  'getEIntra',
  'getExperiment',
  'getExperimentArrayMetrics',
  'getExperimentFilterOptions',
  'getExperimentThermo',
  'getExperimentsWithArrayMetric',
  'getExplorerCatalog',
  'getExportFormats',
  'getFeatureImportance',
  'getGPUStats',
  'getHealth',
  'getInterfaceBatchProgress',
  'getInterfaceMoleculeCell',
  'getInterfaceMoleculeCellPreview',
  'getInterfaceMoleculePreview',
  'getInversePipelineProgress',
  'getInversePipelineResults',
  'getJob',
  'getLayeredAnalysis3D',
  'getLearningCurve',
  'getMetrics',
  'getModelHistory',
  'getMoleculeStructure',
  'getParityPlot',
  'getPropertyByAdditive',
  'getPropertyByTemperature',
  'getQueueStats',
  'getRecoveryCandidates',
  'getRecoveryCheck',
  'getResiduals',
  'getRunningJobs',
  'getScatter3D',
  'getSettings',
  'getStressStrainCurve',
  'getStructureXYZ',
  'getSystemStats',
  'getTemperatureScan',
  'importExperiments',
  'listAdditives',
  'listBinderStudies',
  'listBinderTypes',
  'listCrystalStructures',
  'listExperiments',
  'listInterfaceMoleculeCells',
  'listInterfaceMolecules',
  'listJobs',
  'listLayerSources',
  'listLayeredExperiments',
  'listMolecules',
  'postExplorerAggregate',
  'postExplorerData',
  'precomputeTypingChargeCache',
  'prepareTypingCharge',
  'previewInversePlan',
  'previewLayeredStructure',
  'previewMoleculeComposition',
  'promoteModel',
  'retrainModel',
  'retryExperiment',
  'retryJob',
  'rollbackModel',
  'scanDatabase',
  'submitExperiment',
  'submitLayeredStructure',
  'submitMoleculeExperiment',
  'submitSingleMoleculeBatch',
  'updateSettings',
  'validateBatchJobBinderCell',
]

describe('api/client barrel re-exports', () => {
  test('every expected named export exists and is a function', () => {
    const missing = EXPECTED_NAMED_EXPORTS.filter((name) => typeof client[name] !== 'function')
    expect(missing).toEqual([])
  })

  test('no unexpected named exports leaked in', () => {
    const actualNamed = Object.keys(client).filter((k) => k !== 'default').sort()
    expect(actualNamed).toEqual(EXPECTED_NAMED_EXPORTS)
  })

  test('default export is an axios-like instance with HTTP methods', () => {
    const api = client.default
    expect(api).toBeDefined()
    expect(typeof api.get).toBe('function')
    expect(typeof api.post).toBe('function')
    expect(typeof api.put).toBe('function')
    expect(typeof api.delete).toBe('function')
  })

  test(`total named export count is ${EXPECTED_NAMED_EXPORTS.length}`, () => {
    const actualNamed = Object.keys(client).filter((k) => k !== 'default')
    expect(actualNamed.length).toBe(EXPECTED_NAMED_EXPORTS.length)
  })
})
