import clsx from 'clsx'
import { getQueueStageLabel, getQueueStageVisual } from '../../lib/protocolStages'
import { formatStepK } from '../../lib/formatters'

/**
 * StageTimeline - Renders stage progress bar with label and step counts
 * for a running experiment in the queue panel.
 *
 * @param {object} props
 * @param {string|null} props.currentStage - Current stage key (e.g. 'npt_production')
 * @param {number} props.stageStep - Current step within stage
 * @param {number} props.stageTotalSteps - Total steps in current stage
 * @param {number} props.stagePercent - Stage completion percentage (0-100)
 */
function StageTimeline({ currentStage, stageStep, stageTotalSteps, stagePercent }) {
  const stageVisual = getQueueStageVisual(currentStage)

  return (
    <div className="flex flex-col gap-0.5">
      {/* Stage label + step counts */}
      <div className="flex items-center gap-1 text-[10px] leading-tight">
        <span
          className={clsx(
            'px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap',
            stageVisual.text
          )}
          style={{ backgroundColor: `${stageVisual.bg}4D` }}
        >
          {getQueueStageLabel(currentStage)}
        </span>
        <span className="text-slate-400 font-mono tabular-nums">
          {formatStepK(stageStep)}/{formatStepK(stageTotalSteps)} ({Number(stagePercent || 0).toFixed(0)}%)
        </span>
      </div>
      {/* Progress bar */}
      <div className="w-full h-1 bg-gray-700 rounded mt-0.5">
        <div
          className="h-full rounded transition-all"
          style={{
            width: `${Math.min(stagePercent, 100)}%`,
            backgroundColor: stageVisual.bg,
          }}
        />
      </div>
    </div>
  )
}

export default StageTimeline
