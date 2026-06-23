import clsx from 'clsx'
import { Gauge, MonitorPlay } from 'lucide-react'
import Toggle from './Toggle'

function GPUSection({ settings, gpuData, saving, handleChange, handleGPUToggle }) {
  return (
    <>
      {/* GPU Configuration */}
      <section className="card">
        <div className="card-header flex items-center gap-2">
          <Gauge className="w-5 h-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-white">GPU Configuration</h2>
        </div>
        <div className="card-body space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium">Enable GPU Acceleration</label>
              <p className="text-sm text-slate-400 mt-1">
                Turn off to run simulations on CPU only. Useful when GPUs are unavailable.
              </p>
            </div>
            <Toggle
              checked={settings?.gpu_enabled ?? true}
              onChange={(v) => handleChange('gpu_enabled', v)}
              disabled={saving}
            />
          </div>
        </div>
      </section>

      {/* GPU Selection */}
      <section className="card">
        <div className="card-header flex items-center gap-2">
          <MonitorPlay className="w-5 h-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-white">GPU Selection</h2>
        </div>
        <div className="card-body space-y-4">
          <p className="text-sm text-slate-400">
            Select GPUs to use for simulations. Leave all unchecked to use all available GPUs.
          </p>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {gpuData?.gpus?.map((gpu) => {
              // Sub-threshold (ineligible) GPUs — e.g. an RTX 3050 display card —
              // are shown for transparency but NOT selectable: jobs must never run
              // on a GPU below the VRAM floor. The backend allocator (cap 0) is the
              // authoritative gate; this just keeps the UI from offering it.
              const ineligible = gpu.eligible === false
              const isChecked = !ineligible && (settings?.selected_gpus || []).includes(gpu.id)
              return (
              <div
                key={gpu.id}
                className={clsx(
                  'p-3 rounded-lg border transition-colors',
                  ineligible
                    ? 'cursor-not-allowed opacity-50 bg-slate-800/40 border-slate-700'
                    : 'cursor-pointer ' +
                      (isChecked
                        ? 'bg-blue-500/20 border-blue-500/50'
                        : 'bg-slate-700/50 border-slate-600 hover:border-slate-500')
                )}
                onClick={() => !saving && !ineligible && handleGPUToggle(gpu.id)}
              >
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => {}}
                    disabled={saving || ineligible}
                    className="w-4 h-4 rounded border-slate-500 text-blue-500 focus:ring-blue-500 focus:ring-offset-slate-800"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-white flex items-center gap-1.5">
                      GPU {gpu.id}
                      {ineligible && (
                        <span
                          className="text-[10px] px-1 py-0.5 rounded bg-slate-600/40 text-slate-300"
                          title="Below VRAM threshold — excluded from job allocation (no jobs run here)"
                        >
                          excluded
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-400 truncate">{gpu.name}</div>
                    <div className="text-xs text-slate-500">
                      {gpu.status === 'available' ? (
                        <span className="text-green-400">Available</span>
                      ) : (
                        <span className="text-yellow-400">{gpu.status}</span>
                      )}
                      {' | '}{gpu.utilization?.toFixed(0) ?? 0}% util
                      {gpu.slots_total > 1 && (
                        <span className="text-slate-400">
                          {' | '}{gpu.slots_used ?? 0}/{gpu.slots_total} jobs
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              )
            })}
          </div>

          <div className="text-sm text-slate-400 pt-2 border-t border-slate-700">
            {(settings?.selected_gpus || []).length > 0
              ? `Selected GPUs: ${[...settings.selected_gpus].sort((a, b) => a - b).join(', ')}`
              : 'Using all available GPUs (default)'}
          </div>
        </div>
      </section>
    </>
  )
}

export default GPUSection
