import { Link } from 'react-router-dom'
import { Loader2, RotateCcw, StopCircle, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import { StatusBadge } from '../shared'
import { formatCompactDate, formatElapsedDuration } from '../../lib/formatters'
import StageTimeline from './StageTimeline'

const CANCELABLE_DISPLAY_STATUSES = ['pending', 'queued', 'building', 'ready', 'running', 'analyzing']
const DELETABLE_STATUSES = ['ready', 'completed', 'failed', 'cancelled', 'timeout']

/**
 * ExperimentRow - Renders a single experiment row in the queue table.
 *
 * @param {object} props
 * @param {object} props.exp - Merged experiment data
 * @param {number} props.jobNumber - Display job number
 * @param {boolean} props.selected - Whether this row's checkbox is checked
 * @param {boolean} props.actionLoading - Whether an action is in progress for this experiment
 * @param {Function} props.onSelect - Toggle selection callback
 * @param {Function} props.onCancel - Cancel experiment callback
 * @param {Function} props.onDelete - Delete experiment callback
 */
function ExperimentRow({ exp, jobNumber, selected, actionLoading, onSelect, onCancel, onDelete, onRetry }) {
  return (
    <tr
      className={clsx(
        'text-center',
        exp.displayStatus === 'running' && 'bg-blue-500/5 border-l-2 border-l-blue-500',
        exp.displayStatus === 'building' && 'bg-indigo-500/5 border-l-2 border-l-indigo-500',
        exp.data_age === 'current_session' &&
          !['running', 'building'].includes(exp.displayStatus) &&
          'bg-slate-800/50'
      )}
    >
      <td className="w-[32px] pl-2 pr-0">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onSelect(exp.exp_id)}
          className="w-3.5 h-3.5 rounded border-slate-500 bg-slate-700 text-blue-500 cursor-pointer"
        />
      </td>
      <td className="w-[40px] pl-1 pr-1 text-slate-500 text-center">
        {jobNumber || '-'}
      </td>
      <td className="w-[168px] px-0">
        <Link
          to={`/experiments/${exp.exp_id}`}
          className="text-blue-400 hover:text-blue-300 block truncate"
          title={exp.exp_id}
        >
          {(() => {
            // exp_id parsing:
            // - Binder cell: A1_X1_NA_none_298K_a1b2c3 or A1_X1_NA_SBS_5wt_298K_a1b2c3
            // - Single molecule: SM_U-AS-Thio-0293_293K_a1b2c3
            const parts = exp.exp_id.split('_')
            const binder = parts[0] || ''
            const size = parts[1] || ''
            const aging = parts[2] || ''
            const additive = parts[3] || ''
            const tempPart = parts.find(p => /^\d+K$/.test(p)) || ''
            const metadataTemp = exp.temperature_k ?? exp.temperature_K ?? exp.temperature
            const metadataTempPart = Number.isFinite(Number(metadataTemp))
              ? `${Math.round(Number(metadataTemp))}K`
              : ''
            const displayTempPart = tempPart || metadataTempPart
            const amountPart = parts.find(p => /^\d+wt$/.test(p)) || ''

            if (binder === 'SM') {
              return (
                <span className="flex items-center gap-0.5 flex-wrap">
                  <span className="font-medium text-slate-200">SM</span>
                  {size && <span className="text-slate-400">{size}</span>}
                  {displayTempPart && <span className="text-yellow-400">{displayTempPart}</span>}
                </span>
              )
            }

            return (
              <span className="flex items-center gap-0.5 flex-wrap">
                <span className="font-medium text-slate-200">{binder}</span>
                <span className="text-slate-400">{size}</span>
                <span className="text-orange-400">{aging}</span>
                {additive && additive !== 'none' && (
                  <span className="text-cyan-400">{additive}</span>
                )}
                {amountPart && <span className="text-emerald-400">{amountPart}</span>}
                {displayTempPart && <span className="text-yellow-400">{displayTempPart}</span>}
              </span>
            )
          })()}
        </Link>
      </td>
      <td className="w-[76px] px-0.5">
        <div className="flex flex-col gap-0.5">
          <StatusBadge
            status={exp.displayStatus}
            showIcon={true}
            size="sm"
            className="justify-center min-w-[68px] px-2 text-[8px] lowercase"
          />
          {exp.telemetryStale && (
            <span className="text-[10px] text-amber-400 leading-none">
              telemetry stale
            </span>
          )}
        </div>
      </td>
      <td className="w-[50px] px-1">
        {exp.gpuId !== null && exp.gpuId !== undefined ? (
          <span className="text-cyan-400">{exp.gpuId}</span>
        ) : (
          <span className="text-slate-500">-</span>
        )}
      </td>
      <td className="w-[120px] px-0.5">
        {exp.displayStatus === 'running' ? (
          <StageTimeline
            currentStage={exp.currentStage}
            stageStep={exp.stageStep}
            stageTotalSteps={exp.stageTotalSteps}
            stagePercent={exp.stagePercent}
          />
        ) : exp.displayStatus === 'building' ? (
          <div className="flex items-center gap-1 text-[10px] text-indigo-300">
            <div className="w-2.5 h-2.5 border-2 border-indigo-400/30 border-t-indigo-400 rounded-full animate-spin" />
            <span className="truncate">{exp.buildPhaseLabel || 'Building...'}</span>
            {exp.buildProgressPercent != null && (
              <span className="ml-0.5 font-mono text-indigo-400 whitespace-nowrap">
                {Math.round(exp.buildProgressPercent)}%
              </span>
            )}
          </div>
        ) : exp.status === 'completed' ? (
          <span className="text-green-400 text-xs font-mono">100%</span>
        ) : (
          <span className="text-slate-500 text-xs">-</span>
        )}
      </td>
      <td className="w-[90px] px-0">
        {exp.displayStatus === 'running' && exp.temperature !== null ? (
          <div className="flex flex-col leading-tight">
            <span className="text-cyan-400 whitespace-nowrap">{exp.temperature?.toFixed(0)}K</span>
            <span className="text-green-400 whitespace-nowrap">{exp.density != null ? exp.density.toFixed(3) : '-'}</span>
          </div>
        ) : (
          <span className="text-slate-500">-</span>
        )}
      </td>
      <td className="w-[82px] px-0 text-slate-400 whitespace-nowrap">
        {formatCompactDate(exp.created_at)}
      </td>
      <td className="w-[92px] px-1 text-slate-400 whitespace-nowrap">
        {formatCompactDate(exp.completed_at)}
      </td>
      <td className="w-[96px] px-1 text-slate-300 whitespace-nowrap">
        {exp.pipelineElapsedSeconds != null
          ? formatElapsedDuration(exp.pipelineElapsedSeconds)
          : exp.displayStatus === 'running' && exp.elapsed
            ? exp.elapsed
            : formatElapsedDuration(exp.wallTimeSeconds)}
      </td>
      <td className="w-[80px] px-1">
        <div className="flex items-center justify-center gap-0.5">
          {/* Retry: terminal states (failed, cancelled, timeout) */}
          {['failed', 'cancelled', 'timeout'].includes(exp.status) && onRetry && (
            <button
              onClick={() => onRetry(exp.exp_id)}
              disabled={actionLoading}
              className="p-1 text-slate-400 hover:text-blue-400 hover:bg-slate-700 rounded disabled:opacity-50"
              title="Retry"
            >
              {actionLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4" />
              )}
            </button>
          )}
          {/* Cancel: cancelable statuses (SSOT) */}
          {CANCELABLE_DISPLAY_STATUSES.includes(exp.displayStatus) && (
            <button
              onClick={() => onCancel(exp.exp_id)}
              disabled={actionLoading}
              className="p-1 text-slate-400 hover:text-orange-400 hover:bg-slate-700 rounded disabled:opacity-50"
              title="Stop"
            >
              {actionLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <StopCircle className="w-4 h-4" />
              )}
            </button>
          )}
          {/* Delete: ready + terminal states */}
          {DELETABLE_STATUSES.includes(exp.status) && (
            <button
              onClick={() => onDelete(exp.exp_id)}
              disabled={actionLoading}
              className="p-1 text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded disabled:opacity-50"
              title="Delete"
            >
              {actionLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

export default ExperimentRow
