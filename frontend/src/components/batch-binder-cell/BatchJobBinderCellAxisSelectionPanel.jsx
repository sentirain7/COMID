import clsx from 'clsx'

function BatchJobBinderCellAxisSelectionPanel({
  binderTypeOptions,
  structureSizeOptions,
  agingStateOptions,
  form,
  toggleListField,
  chipButtonClass,
}) {
  return (
    <div className="text-sm text-slate-300 md:col-span-2 flex flex-col">
      <div className="grid grid-cols-1 sm:grid-cols-[1.8fr_1fr_1fr] gap-3 h-full">
        <div className="text-sm text-slate-300 flex flex-col">
          <div className="text-sm font-semibold mb-1">Binder Type</div>
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1">
            <div className="flex flex-nowrap gap-1.5 overflow-x-auto">
              {binderTypeOptions.map((binderType) => (
                <button
                  key={binderType}
                  type="button"
                  onClick={() => toggleListField('binder_types', binderType)}
                  className={clsx(chipButtonClass(form.binder_types.includes(binderType)), 'whitespace-nowrap')}
                  aria-pressed={form.binder_types.includes(binderType)}
                >
                  {binderType}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="text-sm text-slate-300 flex flex-col">
          <div className="text-sm font-semibold mb-1">Structure Size</div>
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1">
            <div className="flex flex-nowrap gap-1.5 overflow-x-auto">
              {structureSizeOptions.map((size) => (
                <button
                  key={size}
                  type="button"
                  onClick={() => toggleListField('structure_sizes', size)}
                  className={clsx(chipButtonClass(form.structure_sizes.includes(size)), 'whitespace-nowrap')}
                  aria-pressed={form.structure_sizes.includes(size)}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="text-sm text-slate-300 flex flex-col">
          <div className="text-sm font-semibold mb-1">Aging State</div>
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1">
            <div className="flex flex-nowrap gap-1.5 overflow-x-auto">
              {agingStateOptions.map((agingState) => (
                <button
                  key={agingState.value}
                  type="button"
                  onClick={() => toggleListField('aging_states', agingState.value)}
                  className={clsx(chipButtonClass(form.aging_states.includes(agingState.value)), 'whitespace-nowrap')}
                  aria-pressed={form.aging_states.includes(agingState.value)}
                >
                  {agingState.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default BatchJobBinderCellAxisSelectionPanel
