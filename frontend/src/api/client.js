// =============================================================================
// API Client — Barrel re-export (sole public entry point)
//
// All consumers import from 'api/client'. Domain logic lives in individual
// modules under src/api/. This file re-exports every named export explicitly
// (no `export *`) so the public surface is fixed and auditable.
// =============================================================================

// Default axios instance
export { default } from './axiosInstance'

// Health
export { getHealth, getRecoveryCheck, getRecoveryCandidates, executeRecoveryAction, executeAllRecoveryActions } from './health'

// Experiments
export { listExperiments, getExperiment, submitExperiment, getExportFormats, exportExperiments, deleteExperiment, cancelExperiment, retryExperiment, batchCancelExperiments, batchDeleteExperiments, batchRetryExperiments, submitSingleMoleculeBatch, getExperimentFilterOptions } from './experiments'

// Jobs
export { listJobs, getJob, cancelJob, deleteJob, retryJob, cleanupOldJobs, deleteAllCompletedJobs } from './jobs'

// Queue
export { getQueueStats } from './queue'

// Metrics
export { getMetrics, getExperimentThermo, getCEDByAdditive, getTemperatureScan, getDensityTemperatureData, getPropertyByTemperature, getPropertyByAdditive, getArrayMetricData, getExperimentArrayMetrics, getArrayMetricCompare, getExperimentsWithArrayMetric } from './metrics'

// Molecules
export { listMolecules, getEIntra, getMoleculeStructure, deleteArtifact, deleteEIntra, getAdminArtifactStatus, adminGenerateArtifact, adminDiagnoseArtifact, getAdminBatchProgress, adminGenerateAll, adminGenerateSelected, adminCancelBatch, adminResetBatch } from './molecules'

// Resources
export { getGPUStats, getRunningJobs, getSystemStats } from './resources'

// Binder Types
export { listBinderTypes, getBinderComposition, listAdditives, submitMoleculeExperiment, previewMoleculeComposition, precomputeTypingChargeCache, checkTypingReadiness, prepareTypingCharge } from './binderTypes'

// Protocol
export { getDefaultStages } from './protocol'

// Crystal
export { listCrystalStructures, getCrystalStructure, getCrystalStructurePreview, createCrystalStructure, deleteCrystalStructure, batchGenerateCrystalSizes, batchGenerateCrystalSizesAsync, getCrystalBatchProgress } from './crystal'

// Interface Molecules
export { listInterfaceMolecules, getInterfaceMoleculePreview, listInterfaceMoleculeCells, getInterfaceMoleculeCell, getInterfaceMoleculeCellPreview, createInterfaceMoleculeCell, deleteInterfaceMoleculeCell, batchGenerateInterfaceMoleculeCells, batchGenerateInterfaceMoleculeCellsAsync, getInterfaceBatchProgress } from './interfaceMolecules'

// Layered
export { listLayerSources, previewLayeredStructure, submitLayeredStructure, listLayeredExperiments, getStressStrainCurve, getLayeredAnalysis3D } from './layered'

// Analysis
export { getAnalysisEmbedding, getAnalysisMoleculeImpact, getBinderCellXYSummary, getScatter3D } from './analysis'

// Structure
export { getStructureXYZ, getAvailableStages } from './structure'

// MLOps
export { getChampionModel, getModelHistory, retrainModel, promoteModel, rollbackModel, checkModelDrift, getParityPlot, getFeatureImportance, getResiduals, getLearningCurve, getDataCoverage, getDataQuality, getStructuralMLStatus, runStructuralEval, runStructuralTrain } from './mlops'

// Batch Job
export { validateBatchJobBinderCell, createBatchJobBinderCell } from './batchJob'

// Scan Database
export { scanDatabase, importExperiments, deleteScannedExperiments } from './scanDatabase'

// Binder Studies
export { listBinderStudies, getBinderStudy, getBinderStudyResults, deleteBinderStudy } from './binderStudies'

// Analysis Explorer
export { getExplorerCatalog, postExplorerData, postExplorerAggregate } from './analysisExplorer'

// Inverse Design Pipeline
export { previewInversePlan, approveInversePlan, getInversePipelineProgress, getInversePipelineResults } from './inversePipeline'

// Settings
export { getSettings, updateSettings } from './settings'

// E_inter Compute
export { getEInterRecommendation, createCpuRerunJob, getCpuRerunJobStatus } from './eInterCompute'
