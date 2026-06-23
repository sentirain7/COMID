import clsx from 'clsx'
import { TEMPERATURE_PRESET_OPTIONS } from '../../lib/temperature'
import { chipButtonClass } from '../../lib/chipButton'

function TemperatureSelectorHybrid({
  value,
  onChange,
  presets = TEMPERATURE_PRESET_OPTIONS,
  presetColumns = 5,
  min = 200,
  max = 500,
  compact = false,
  title = 'Temperature (K)',
  showTitle = true,
}) {
  const hasNumericValue =
    value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
  const numericValue = hasNumericValue ? Number(value) : null
  const inlineInputInPresetGrid = compact && presetColumns === 7
  const presetGridClass =
    presetColumns === 7
      ? 'grid-cols-7'
      : presetColumns === 6
        ? 'grid-cols-6'
        : presetColumns === 8
          ? 'grid-cols-8'
          : 'grid-cols-5'

  const handlePresetClick = (temp) => {
    const selected = numericValue !== null && numericValue === Number(temp)
    if (selected) {
      onChange?.(null, 'preset')
      return
    }
    onChange?.(Number(temp), 'preset')
  }

  const handleInputChange = (event) => {
    const raw = event.target.value
    if (raw === '') {
      onChange?.(null, 'input')
      return
    }
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) {
      onChange?.(parsed, 'input')
    }
  }

  return (
    <div className="space-y-1">
      {showTitle && <span className={clsx('text-slate-400', compact ? 'text-[11px]' : 'text-xs')}>{title}</span>}
      <div className={clsx('rounded-lg border border-slate-700 bg-slate-800/40', compact ? 'p-2' : 'p-3')}>
        <div className={clsx('grid', presetGridClass, compact ? 'gap-1' : 'gap-1.5')}>
          {presets.map((temp) => {
            const selected = numericValue !== null && numericValue === Number(temp)
            return (
              <button
                key={temp}
                type="button"
                onClick={() => handlePresetClick(temp)}
                className={chipButtonClass(selected)}
                aria-pressed={selected}
              >
                {temp}K
              </button>
            )
          })}
          {inlineInputInPresetGrid && (
            <div className="col-start-4 col-span-4 flex flex-col items-end gap-0.5">
              <input
                type="number"
                min={min}
                max={max}
                step={1}
                value={numericValue ?? ''}
                onChange={handleInputChange}
                aria-label={title}
                placeholder="Select or enter temperature"
                className="input w-full min-w-0 !h-[30px] !min-h-0 px-2 !py-0 text-[11px] leading-none text-center placeholder:text-[10px] placeholder:text-slate-500 bg-slate-700/60 border-slate-600"
              />
            </div>
          )}
        </div>
        {!inlineInputInPresetGrid && (
          <div className={clsx('flex items-center justify-center gap-2', compact ? 'mt-1.5' : 'mt-2')}>
            <input
              type="number"
              min={min}
              max={max}
              step={1}
              value={numericValue ?? ''}
              onChange={handleInputChange}
              aria-label={title}
              placeholder="Select or enter temperature"
              className={clsx(
                'input text-center placeholder:text-slate-500 bg-slate-700/60',
                compact ? 'w-20 py-1 text-xs' : 'w-24 py-1.5 text-sm'
              )}
            />
          </div>
        )}
      </div>
    </div>
  )
}

export default TemperatureSelectorHybrid
