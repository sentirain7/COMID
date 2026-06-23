import { Component } from 'react'
import { AlertCircle } from 'lucide-react'

/**
 * Error Boundary for Single Molecule screens.
 *
 * Catches React render exceptions in child components and displays
 * an error message instead of leaving a blank screen.
 */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    // Log to console for developer inspection
    console.error('[SingleMolecule ErrorBoundary] caught:', error)
    console.error('[SingleMolecule ErrorBoundary] componentStack:', errorInfo?.componentStack)
    this.setState({ errorInfo })
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  render() {
    if (this.state.hasError) {
      const errMsg = this.state.error?.message || String(this.state.error || 'Unknown error')
      const stack = this.state.error?.stack || ''
      const componentStack = this.state.errorInfo?.componentStack || ''
      return (
        <div className="card p-6 m-4">
          <div className="flex items-start gap-3 mb-4">
            <AlertCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold text-red-400 mb-1">Render error</h2>
              <p className="text-sm text-slate-300">{errMsg}</p>
            </div>
          </div>
          {stack && (
            <details className="mb-3" open>
              <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-300">
                Stack trace
              </summary>
              <pre className="mt-2 text-[10px] text-slate-500 bg-slate-900/60 p-2 rounded overflow-x-auto whitespace-pre-wrap">
                {stack}
              </pre>
            </details>
          )}
          {componentStack && (
            <details className="mb-3">
              <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-300">
                Component stack
              </summary>
              <pre className="mt-2 text-[10px] text-slate-500 bg-slate-900/60 p-2 rounded overflow-x-auto whitespace-pre-wrap">
                {componentStack}
              </pre>
            </details>
          )}
          <button
            type="button"
            onClick={this.handleReset}
            className="px-4 py-2 bg-blue-500/20 text-blue-400 rounded hover:bg-blue-500/30 text-sm"
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
