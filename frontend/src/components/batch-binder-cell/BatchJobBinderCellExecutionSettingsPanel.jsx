import { AppliedForceFieldNote } from '../shared'

export function BatchJobTemperaturePanel({
  temperatureOptions,
  form,
  toggleTemperature,
  toggleTemperaturePriority,
  chipButtonClass,
}) {
  return (
    <div className="text-sm text-slate-300 flex flex-col">
      <div className="text-sm font-semibold mb-1">Temperature (K)</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1">
        <div className="grid grid-cols-5 gap-1.5">
          {temperatureOptions.map((temp) => {
            const selected = form.temperatures_k.includes(temp)
            const prioritized = form.temperature_priority.includes(temp)
            return (
              <button
                key={temp}
                type="button"
                onClick={() => toggleTemperature(temp)}
                onDoubleClick={() => toggleTemperaturePriority(temp)}
                className={chipButtonClass(
                  prioritized || selected,
                  prioritized ? 'amber' : 'blue',
                )}
                aria-pressed={selected}
                title={prioritized ? 'Priority temperature' : 'Double-click to set as priority'}
              >
                {temp}K{prioritized ? '*' : ''}
              </button>
            )
          })}
        </div>
        <p className="text-[10px] text-slate-500 mt-2">
          Priority (double-click): {form.temperature_priority.length > 0 ? form.temperature_priority.join(', ') : 'none'}
        </p>
      </div>
    </div>
  )
}

export function BatchJobFFDensityPanel({
  ffType,
  form,
  setForm,
  additiveRoutes = [],
}) {
  const handleInitialDensityChange = (e) => {
    const value = Math.max(0.1, Math.min(2.0, Number(e.target.value) || 0.2))
    setForm((prev) => ({ ...prev, initial_density: value }))
  }

  return (
    <div className="text-sm text-slate-300 flex flex-col">
      <div className="text-sm font-semibold mb-1">Force Field</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
        <AppliedForceFieldNote ffType={ffType} additiveRoutes={additiveRoutes} />
      </div>
      <div className="text-sm font-semibold mt-2 mb-1">Initial Density (g/cm3)</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
        <input
          type="number"
          min={0.1}
          max={2.0}
          step={0.1}
          value={form.initial_density ?? 0.2}
          onChange={handleInitialDensityChange}
          className="input w-full h-7 py-0 text-xs"
          aria-label="Initial Density"
        />
        <p className="text-[10px] text-slate-500 mt-1">Packmol packing density</p>
      </div>
    </div>
  )
}

export function BatchJobSeedCachePanel({
  form,
  setForm,
  defaultEIntraMethodLabel,
  effectiveEIntraMethodLabel,
  eIntraMethodOverride,
  setEIntraMethodOverride,
  eIntraMethodOptions,
}) {
  return (
    <div className="text-sm text-slate-300 flex flex-col">
      <div className="text-sm font-semibold mb-1">Seed</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 mb-2">
        <input
          type="number"
          min={0}
          step={1}
          value={form.seed}
          onChange={(e) => setForm((prev) => ({ ...prev, seed: e.target.value }))}
          className="input w-full h-7 py-0 text-xs"
          placeholder="YYYYMMDD"
          aria-label="Seed"
        />
      </div>
      <div className="text-sm font-semibold mb-1">E_intra Method</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 space-y-1.5">
        <div className="text-[10px] text-slate-500">Default: {defaultEIntraMethodLabel}</div>
        <select
          className="input w-full h-8 py-1 text-xs"
          value={eIntraMethodOverride}
          onChange={(e) => setEIntraMethodOverride(e.target.value)}
          aria-label="E_intra Method Override"
        >
          {eIntraMethodOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <div className="text-[10px] text-slate-500">Submit: {effectiveEIntraMethodLabel}</div>
      </div>
    </div>
  )
}
