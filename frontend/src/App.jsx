import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout/Layout'
import Dashboard from './components/Dashboard'
import Jobs from './components/Jobs'
import Molecules from './components/Molecules'
import Experiments from './components/Experiments'
import Settings from './components/Settings'
import Analysis from './components/Analysis'
import MLOps from './components/MLOps'
import RecoveryDialog from './components/RecoveryDialog'
import { useRecoveryCheck } from './hooks/useApi'
import {
  BatchSingleMoleculePage,
  BinderAnalysisPage,
  BinderCellBatchJobPage,
  BinderCellSingleJobPage,
  BinderCellsPage,
  CrystalStructuresPage,
  InterfaceMoleculesPage,
  InverseDesignPage,
  LayeredStructurePage,
  LayeredStructuresPage,
  SingleMoleculePage,
} from './pages'
import { ROUTE_KEYS, ROUTE_META } from './navigation/routeMeta'

function App() {
  const [showRecoveryDialog, setShowRecoveryDialog] = useState(false)
  const { data: recoveryCheck } = useRecoveryCheck()

  useEffect(() => {
    if (recoveryCheck?.needs_recovery) {
      setShowRecoveryDialog(true)
    }
  }, [recoveryCheck])

  return (
    <>
      <Layout>
        <Routes>
          <Route path={ROUTE_META[ROUTE_KEYS.DASHBOARD].path} element={<Dashboard />} />
          <Route path={ROUTE_META[ROUTE_KEYS.BINDER_CELLS_DATABASE].path} element={<BinderCellsPage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.SINGLE_JOB_SINGLE_MOLECULE].path} element={<SingleMoleculePage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.SINGLE_JOB_BINDER_CELL].path} element={<BinderCellSingleJobPage />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/experiments/:expId" element={<Experiments />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path={ROUTE_META[ROUTE_KEYS.MOLECULES].path} element={<Molecules />} />
          {/* v00.99.41+ permanent redirect; no dedicated page — canonical
              FF artifact surface is /molecules. Kept as legacy alias for
              external bookmarks. */}
          <Route path={ROUTE_META[ROUTE_KEYS.FF_PARAMETERS].path} element={<Navigate to={ROUTE_META[ROUTE_KEYS.MOLECULES].path} replace />} />
          <Route path={ROUTE_META[ROUTE_KEYS.INTERFACE_MOLECULES_DATABASE].path} element={<InterfaceMoleculesPage mode="library" />} />
          <Route path={ROUTE_META[ROUTE_KEYS.CRYSTAL_STRUCTURES_DATABASE].path} element={<CrystalStructuresPage mode="library" />} />
          <Route path={ROUTE_META[ROUTE_KEYS.LAYERED_STRUCTURES_DATABASE].path} element={<LayeredStructuresPage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.SINGLE_JOB_INTERFACE_MOLECULES].path} element={<InterfaceMoleculesPage mode="create" />} />
          <Route path={ROUTE_META[ROUTE_KEYS.SINGLE_JOB_CRYSTAL_STRUCTURES].path} element={<CrystalStructuresPage mode="create" />} />
          <Route path={ROUTE_META[ROUTE_KEYS.SINGLE_JOB_LAYERED_STRUCTURE].path} element={<LayeredStructurePage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.ANALYSIS].path} element={<Analysis />} />
          <Route path={ROUTE_META[ROUTE_KEYS.BINDER_ANALYSIS].path} element={<BinderAnalysisPage />} />
          <Route path={`${ROUTE_META[ROUTE_KEYS.BINDER_ANALYSIS].path}/:studyId`} element={<BinderAnalysisPage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.MLOPS].path} element={<MLOps />} />
          <Route path={ROUTE_META[ROUTE_KEYS.INVERSE_DESIGN].path} element={<InverseDesignPage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.BATCH_JOB_SINGLE_MOLECULE].path} element={<BatchSingleMoleculePage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.BATCH_JOB_BINDER_CELL].path} element={<BinderCellBatchJobPage />} />
          <Route path={ROUTE_META[ROUTE_KEYS.SETTINGS].path} element={<Settings />} />
        </Routes>
      </Layout>

      <RecoveryDialog
        isOpen={showRecoveryDialog}
        onClose={() => setShowRecoveryDialog(false)}
      />
    </>
  )
}

export default App
