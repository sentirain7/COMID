import { useEffect, useState } from 'react'
import { XMarkIcon, ExclamationTriangleIcon, CheckCircleIcon, XCircleIcon } from '@heroicons/react/24/outline'
import {
  useExecuteAllRecoveryActions,
  useExecuteRecoveryAction,
  useRecoveryCandidates,
} from '../hooks/useApi'

/**
 * Recovery Dialog Component
 *
 * Shows a modal dialog when orphaned/stale processes are detected.
 * Allows users to review and take action on each candidate.
 */
function RecoveryDialog({ isOpen, onClose }) {
  const [results, setResults] = useState({})
  const [executing, setExecuting] = useState({})
  const { data, loading, execute } = useRecoveryCandidates(isOpen)
  const executeActionMutation = useExecuteRecoveryAction()
  const executeAllMutation = useExecuteAllRecoveryActions()

  const candidates = data || []

  useEffect(() => {
    if (isOpen) {
      execute()
    }
  }, [isOpen, execute])

  const executeAction = async (expId, action) => {
    setExecuting((prev) => ({ ...prev, [expId]: true }))

    try {
      const result = await executeActionMutation.mutateAsync({ exp_id: expId, action })
      setResults((prev) => ({ ...prev, [expId]: result }))
      execute()
    } catch (error) {
      setResults((prev) => ({
        ...prev,
        [expId]: { success: false, message: 'Request failed', error: error.message },
      }))
    } finally {
      setExecuting((prev) => ({ ...prev, [expId]: false }))
    }
  }

  const executeAllRecommended = async () => {
    try {
      const allResults = await executeAllMutation.mutateAsync()
      const resultMap = {}
      allResults.forEach((item) => {
        resultMap[item.exp_id] = item
      })
      setResults(resultMap)
      execute()
    } catch (error) {
      console.error('Failed to execute all recommended:', error)
    }
  }

  const getStateColor = (state) => {
    switch (state) {
      case 'running':
        return 'text-green-400'
      case 'stale':
        return 'text-yellow-400'
      case 'terminated':
        return 'text-red-400'
      case 'orphaned':
        return 'text-orange-400'
      default:
        return 'text-slate-400'
    }
  }

  const getActionButton = (action, expId, isRecommended) => {
    const colors = {
      resume: 'bg-green-600 hover:bg-green-500',
      recover: 'bg-blue-600 hover:bg-blue-500',
      restart: 'bg-yellow-600 hover:bg-yellow-500',
      abandon: 'bg-red-600 hover:bg-red-500',
      ignore: 'bg-slate-600 hover:bg-slate-500',
    }

    const labels = {
      resume: 'Resume',
      recover: 'Recover Results',
      restart: 'Restart',
      abandon: 'Abandon',
      ignore: 'Ignore',
    }

    return (
      <button
        key={action}
        onClick={() => executeAction(expId, action)}
        disabled={executing[expId]}
        className={`px-3 py-1.5 text-sm font-medium rounded ${colors[action] || colors.ignore} ${
          isRecommended ? 'ring-2 ring-white/30' : ''
        } disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        {executing[expId] ? '...' : labels[action] || action}
        {isRecommended && ' (Recommended)'}
      </button>
    )
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-slate-800 rounded-xl shadow-2xl max-w-4xl w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <ExclamationTriangleIcon className="h-6 w-6 text-yellow-400" />
            <div>
              <h2 className="text-xl font-semibold text-white">Process Recovery</h2>
              <p className="text-sm text-slate-400">
                {candidates.length > 0
                  ? `${candidates.length} process(es) may need recovery`
                  : 'No recovery needed'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white"
          >
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
          ) : candidates.length === 0 ? (
            <div className="text-center py-12">
              <CheckCircleIcon className="h-12 w-12 text-green-400 mx-auto mb-4" />
              <p className="text-white font-medium">All processes recovered</p>
              <p className="text-slate-400 text-sm mt-1">
                No further action is required.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {candidates.map((candidate) => (
                <div
                  key={candidate.exp_id}
                  className="bg-slate-700/50 rounded-lg p-4"
                >
                  {/* Candidate Header */}
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm text-white">
                          {candidate.exp_id}
                        </span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full bg-slate-600 ${getStateColor(
                            candidate.state
                          )}`}
                        >
                          {candidate.state}
                        </span>
                      </div>
                      <p className="text-sm text-slate-400 mt-1">
                        {candidate.reason}
                      </p>
                    </div>
                    {results[candidate.exp_id] && (
                      <div
                        className={`flex items-center gap-1 text-sm ${
                          results[candidate.exp_id].success
                            ? 'text-green-400'
                            : 'text-red-400'
                        }`}
                      >
                        {results[candidate.exp_id].success ? (
                          <CheckCircleIcon className="h-4 w-4" />
                        ) : (
                          <XCircleIcon className="h-4 w-4" />
                        )}
                        {results[candidate.exp_id].message}
                      </div>
                    )}
                  </div>

                  {/* Candidate Details */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
                    <div>
                      <span className="text-slate-500">PID:</span>
                      <span className="text-white ml-2">{candidate.pid}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">Host:</span>
                      <span className="text-white ml-2">{candidate.hostname}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">GPU:</span>
                      <span className="text-white ml-2">
                        {candidate.gpu_id !== null ? `GPU ${candidate.gpu_id}` : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500">Progress:</span>
                      <span className="text-white ml-2">
                        {candidate.progress_percent !== null
                          ? `${candidate.progress_percent.toFixed(1)}%`
                          : 'Unknown'}
                      </span>
                    </div>
                  </div>

                  {/* Progress Bar */}
                  {candidate.progress_percent !== null && (
                    <div className="mb-4">
                      <div className="h-2 bg-slate-600 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500 rounded-full transition-all"
                          style={{ width: `${candidate.progress_percent}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex flex-wrap gap-2">
                    {candidate.available_actions?.map((action) =>
                      getActionButton(
                        action,
                        candidate.exp_id,
                        action === candidate.recommended_action
                      )
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-slate-700 flex items-center justify-between">
          <button
            onClick={executeAllRecommended}
            disabled={
              loading ||
              candidates.length === 0 ||
              executeAllMutation.isPending
            }
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {executeAllMutation.isPending
              ? 'Executing...'
              : 'Execute All Recommended'}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white font-medium rounded-lg"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default RecoveryDialog
