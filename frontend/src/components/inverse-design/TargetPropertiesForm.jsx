import {
  INVERSE_AGGREGATE_MATERIALS,
  INVERSE_TARGET_DIRECTIONS,
  INVERSE_TARGET_METRICS,
  STRUCTURE_SIZE_OPTIONS,
} from '../../lib/constants'
import { useAdditives } from '../../hooks/useAdditives'
import { useBinderTypes } from '../../hooks/useBinderTypes'
import { getMetricInfo, isInterfaceMetric } from './planRequest'

function TargetRow({ target, onChange, onRemove }) {
  const metric = getMetricInfo(target.metric_name)
  return (
    <div className="flex flex-wrap items-center gap-2 bg-slate-700/30 rounded p-2">
      <select
        aria-label="target-metric"
        value={target.metric_name}
        onChange={(e) => onChange({ ...target, metric_name: e.target.value })}
        className="bg-slate-800 text-slate-200 text-sm rounded px-2 py-1"
      >
        {INVERSE_TARGET_METRICS.map((m) => (
          <option key={m.name} value={m.name}>
            {m.label} ({m.unit})
          </option>
        ))}
      </select>
      <select
        aria-label="target-direction"
        value={target.direction}
        onChange={(e) => onChange({ ...target, direction: e.target.value })}
        className="bg-slate-800 text-slate-200 text-sm rounded px-2 py-1"
      >
        {INVERSE_TARGET_DIRECTIONS.map((d) => (
          <option key={d.value} value={d.value}>
            {d.label}
          </option>
        ))}
      </select>
      <input
        aria-label="target-min"
        type="number"
        step="any"
        placeholder="min"
        value={target.target_min ?? ''}
        onChange={(e) =>
          onChange({
            ...target,
            target_min: e.target.value === '' ? null : Number(e.target.value),
          })
        }
        className="w-24 bg-slate-800 text-slate-200 text-sm rounded px-2 py-1"
      />
      <span className="text-slate-500 text-xs">~</span>
      <input
        aria-label="target-max"
        type="number"
        step="any"
        placeholder="max"
        value={target.target_max ?? ''}
        onChange={(e) =>
          onChange({
            ...target,
            target_max: e.target.value === '' ? null : Number(e.target.value),
          })
        }
        className="w-24 bg-slate-800 text-slate-200 text-sm rounded px-2 py-1"
      />
      <span className="text-slate-500 text-xs">{metric.unit}</span>
      <button
        type="button"
        onClick={onRemove}
        className="ml-auto text-slate-400 hover:text-red-400 text-sm"
      >
        ✕
      </button>
    </div>
  )
}

/**
 * Wizard ① — target property input (plan §8).
 *
 * Minimal-input principle: accept only the target property list + temperature +
 * aggregate (for interface targets) + additive allowance + moisture-damage flag.
 * Everything else is the backend policy SSOT.
 */
function TargetPropertiesForm({ value, onChange, onSubmit, submitting, error }) {
  const { additives } = useAdditives()
  const { binderTypes } = useBinderTypes()
  const {
    targets,
    temperatureK,
    aggregates,
    binderType,
    structureSize,
    includeAdditive,
    additiveType,
    moistureDamage,
  } = value

  const hasInterfaceTarget = targets.some((t) => isInterfaceMetric(t.metric_name))

  const update = (patch) => onChange({ ...value, ...patch })

  const updateTarget = (idx, next) =>
    update({ targets: targets.map((t, i) => (i === idx ? next : t)) })

  const addTarget = () =>
    update({
      targets: [
        ...targets,
        { metric_name: INVERSE_TARGET_METRICS[0].name, direction: 'maximize', target_min: null, target_max: null },
      ],
    })

  const removeTarget = (idx) => update({ targets: targets.filter((_, i) => i !== idx) })

  const toggleAggregate = (material) =>
    update({
      aggregates: aggregates.includes(material)
        ? aggregates.filter((m) => m !== material)
        : [...aggregates, material],
    })

  const canSubmit =
    targets.length > 0 &&
    targets.every((t) => t.target_min != null || t.target_max != null) &&
    (!hasInterfaceTarget || aggregates.length > 0)

  return (
    <div className="space-y-4">
      <section>
        <h3 className="text-slate-200 font-semibold mb-2">Target properties</h3>
        <div className="space-y-2">
          {targets.map((t, i) => (
            <TargetRow
              key={i}
              target={t}
              onChange={(next) => updateTarget(i, next)}
              onRemove={() => removeTarget(i)}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={addTarget}
          className="mt-2 text-sm text-sky-400 hover:text-sky-300"
        >
          + Add target
        </button>
        {targets.length > 0 && !canSubmit && (
          <p className="text-amber-400 text-xs mt-1">
            Specify min or max for each target
            {hasInterfaceTarget ? ' (interface targets require at least one aggregate)' : ''}.
          </p>
        )}
      </section>

      <section className="flex flex-wrap gap-6">
        <label className="text-sm text-slate-300">
          Binder type
          <select
            aria-label="binder-type"
            value={binderType || ''}
            onChange={(e) => update({ binderType: e.target.value })}
            className="ml-2 bg-slate-800 text-slate-200 rounded px-2 py-1"
          >
            {binderTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm text-slate-300">
          Structure size
          <select
            aria-label="structure-size"
            value={structureSize || ''}
            onChange={(e) => update({ structureSize: e.target.value })}
            className="ml-2 bg-slate-800 text-slate-200 rounded px-2 py-1"
          >
            {STRUCTURE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm text-slate-300">
          Temperature (K)
          <input
            aria-label="temperature-k"
            type="number"
            value={temperatureK}
            onChange={(e) => update({ temperatureK: Number(e.target.value) })}
            className="ml-2 w-24 bg-slate-800 text-slate-200 rounded px-2 py-1"
          />
        </label>

        <label className="text-sm text-slate-300 flex items-center gap-2">
          <input
            type="checkbox"
            aria-label="include-additive"
            checked={includeAdditive}
            onChange={(e) => update({ includeAdditive: e.target.checked })}
          />
          Allow additive
        </label>
        {includeAdditive && (
          <select
            aria-label="additive-type"
            value={additiveType || ''}
            onChange={(e) => update({ additiveType: e.target.value || null })}
            className="bg-slate-800 text-slate-200 text-sm rounded px-2 py-1"
          >
            <option value="">— explore all —</option>
            {additives.map((a) => (
              <option key={a.mol_id} value={a.mol_id}>
                {a.display_name || a.mol_id}
              </option>
            ))}
          </select>
        )}

        <label className="text-sm text-slate-300 flex items-center gap-2">
          <input
            type="checkbox"
            aria-label="moisture-damage"
            checked={moistureDamage}
            onChange={(e) => update({ moistureDamage: e.target.checked })}
          />
          Moisture damage (wet/dry ER)
        </label>
      </section>

      {hasInterfaceTarget && (
        <section>
          <h4 className="text-slate-300 text-sm font-semibold mb-1">
            Aggregate (crystal) — interface targets
          </h4>
          <div className="flex flex-wrap gap-2">
            {INVERSE_AGGREGATE_MATERIALS.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => toggleAggregate(m)}
                className={`px-2 py-1 rounded text-sm ${
                  aggregates.includes(m)
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-700 text-slate-300'
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </section>
      )}

      {error && <p className="text-red-400 text-sm">{String(error)}</p>}

      <button
        type="button"
        disabled={!canSubmit || submitting}
        onClick={onSubmit}
        className="px-4 py-2 rounded bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-white text-sm font-semibold"
      >
        {submitting ? 'Generating plan…' : 'Preview plan'}
      </button>
    </div>
  )
}

export default TargetPropertiesForm
