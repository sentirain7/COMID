import ErrorBoundary from '../components/single-molecule/ErrorBoundary'
import BatchSingleMoleculeScreen from '../components/BatchSingleMoleculeScreen'

export default function BatchSingleMoleculePage() {
  return (
    <ErrorBoundary>
      <BatchSingleMoleculeScreen />
    </ErrorBoundary>
  )
}
