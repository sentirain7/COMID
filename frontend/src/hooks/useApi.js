/**
 * Barrel re-export — all API hooks.
 *
 * Existing `import { ... } from '../hooks/useApi'` paths remain valid.
 */

export { useApi, usePolling } from './useApiCore'
export { useQueueStats, useQueueStatsLive } from './useApiQueue'
export {
  useBatchCancelExperiments,
  useBatchDeleteExperiments,
  useBatchRetryExperiments,
  useCancelExperiment,
  useDeleteExperiment,
  useExperimentDetail,
  useExperimentMetrics,
  useSubmitExperiment,
  useExperiments,
  useExperimentFilterOptions,
  useExperimentThermo,
  useRetryExperiment,
} from './useApiExperiments'
export {
  useCancelJob,
  useDeleteAllCompletedJobs,
  useDeleteJob,
  useJobs,
  useRetryJob,
} from './useApiJobs'
export { useGPUStats, useHealth, useRunningJobs, useSystemStats } from './useApiResources'
export {
  useAnalysisEmbedding,
  useArrayMetricCompare,
  useArrayMetricData,
  useBinderCellXYSummary,
  useCEDByAdditive,
  useDensityTemperature,
  useExperimentArrayMetrics,
  useExperimentsWithArrayMetric,
  useMoleculeImpact,
  usePropertyByAdditive,
  usePropertyByTemperature,
  useScatter3D,
} from './useApiAnalysis'
export {
  useExecuteAllRecoveryActions,
  useExecuteRecoveryAction,
  useRecoveryCandidates,
  useRecoveryCheck,
  useSettings,
} from './useApiSettings'

export {
  useChampionModel,
  useDataCoverage,
  useDataQuality,
  useFeatureImportance,
  useLearningCurve,
  useModelDrift,
  useModelHistory,
  useParityPlot,
  usePromoteModel,
  useResiduals,
  useRetrainModel,
  useStructuralEval,
  useStructuralMLStatus,
  useStructuralTrain,
  useRollbackModel,
} from './useApiMlops'

export {
  useCreateBatchJobBinderCell,
  useValidateBatchJobBinderCell,
} from './useApiBatchJobBinderCell'

export {
  useCreateCrystalStructure,
  useCrystalStructurePreview,
  useCrystalStructures,
  useDeleteCrystalStructure,
} from './useApiCrystalStructures'
export {
  useLayeredAnalysis3D,
  useLayeredExperiments,
  useLayeredStructurePreview,
  useLayeredStructureSubmit,
  useLayerSources,
  useStressStrainCurve,
} from './useApiLayeredStructures'
export { useExperimentEvents } from './useApiExperimentEvents'

export { useDeleteScannedExperiments, useImportExperiments, useScanDatabase } from './useApiScanDatabase'

export {
  useDeleteArtifact,
  useAdminArtifactStatus,
  useAdminGenerateArtifact,
  useAdminDiagnoseArtifact,
  useAdminBatchProgress,
  useAdminGenerateAll,
  useAdminGenerateSelected,
  useAdminCancelBatch,
  useAdminResetBatch,
} from './useArtifacts'

export {
  useBinderStudies,
  useBinderStudyDetail,
  useBinderStudyResults,
  useDeleteBinderStudy,
} from './useApiBinderAnalysis'

// Analysis Explorer
export {
  useExplorerCatalog,
  useExplorerData,
  useExplorerAggregate,
} from './useApiAnalysisExplorer'

// E_inter Compute
export {
  useEInterRecommendation,
  useCreateCpuRerunJob,
  useCpuRerunJobStatus,
} from './useApiEInterCompute'

// Inverse Design Pipeline
export {
  usePreviewInversePlan,
  useApproveInversePlan,
  useInversePipelineProgress,
  useInversePipelineResults,
} from './useApiInversePipeline'
