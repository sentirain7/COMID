import clsx from 'clsx'
import ProtocolTimeline from '../ProtocolTimeline'
import { AGING_STATE_OPTIONS, STRUCTURE_SIZE_OPTIONS } from '../../lib/constants'

function BinderSelectionRow({
  selectedStages,
  timelineStageConfig,
  binderTypes,
  binderType,
  setBinderType,
  enterCustomMode,
  isCustomMode,
  structureSize,
  setStructureSize,
  agingState,
  setAgingState,
  chipButtonClass,
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-stretch">
      <div className="text-sm text-slate-300 md:col-span-2 flex flex-col">
        <div className="text-sm font-semibold mb-1">Protocol Timeline</div>
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1">
          <ProtocolTimeline
            selectedStages={selectedStages}
            stageConfig={timelineStageConfig}
            legendPosition="inline"
          />
        </div>
      </div>
      <div className="text-sm text-slate-300 md:col-span-2 flex flex-col">
        <div className="grid grid-cols-1 sm:grid-cols-[1.8fr_1fr_1fr] gap-3 h-full">
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Binder Type</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 flex-1">
              <div className="flex flex-nowrap gap-1.5 overflow-x-auto">
                {binderTypes.map((bt) => (
                  <button
                    key={bt.name}
                    type="button"
                    onClick={() => setBinderType(bt.name)}
                    className={clsx(chipButtonClass(binderType === bt.name), 'whitespace-nowrap')}
                  >
                    {bt.name}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={enterCustomMode}
                  className={clsx(chipButtonClass(isCustomMode), 'whitespace-nowrap')}
                >
                  Custom
                </button>
              </div>
            </div>
          </div>
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Structure Size</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 flex-1">
              <div className="flex flex-nowrap gap-1.5 overflow-x-auto">
                {STRUCTURE_SIZE_OPTIONS.map((size) => (
                  <button
                    key={size}
                    type="button"
                    onClick={() => setStructureSize(size)}
                    className={clsx(chipButtonClass(structureSize === size), 'whitespace-nowrap')}
                  >
                    {size}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="text-sm text-slate-300 flex flex-col">
            <div className="text-sm font-semibold mb-1">Aging State</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 flex-1">
              <div className="flex flex-nowrap gap-1.5 overflow-x-auto">
                {AGING_STATE_OPTIONS.map((state) => (
                  <button
                    key={state.value}
                    type="button"
                    onClick={() => setAgingState(state.value)}
                    className={clsx(chipButtonClass(agingState === state.value), 'whitespace-nowrap')}
                  >
                    {state.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default BinderSelectionRow
