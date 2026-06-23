import ErrorBoundary from '../components/single-molecule/ErrorBoundary'
import SingleMoleculeScreen from '../components/SingleMoleculeScreen'

export default function SingleMoleculePage() {
  return (
    <ErrorBoundary>
      <SingleMoleculeScreen />
    </ErrorBoundary>
  )
}
