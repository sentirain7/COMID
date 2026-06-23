import clsx from 'clsx'
import { chipButtonClass } from '../../lib/chipButton'
import { SECTION_TITLE_CLASS } from './config'
import LayerChecksPanel from './LayerChecksPanel'

function LayerSettingsPanel({
  ffType,
  setFfType,
  pressureAtm,
  setPressureAtm,
  xyTolerance,
  setXyTolerance,
  xyToZRatio,
  setXyToZRatio,
  zVacuum,
  setZVacuum,
  seed,
  setSeed,
  defaultEIntraMethodLabel,
  effectiveEIntraMethodLabel,
  eIntraMethodOverride,
  setEIntraMethodOverride,
  eIntraMethodOptions,
  // checks
  previewData,
}) {
  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Left: Layer Settings (compact) */}
        <div className="space-y-2">
          <div className="text-sm text-slate-300 flex flex-col">
            <div className={SECTION_TITLE_CLASS}>Layer Settings</div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
              <div className="grid grid-cols-2 gap-1.5 md:grid-cols-4">
                <label className="space-y-0.5 block">
                  <span className="text-[10px] text-slate-400">Pressure (atm)</span>
                  <input
                    type="number"
                    className="input text-[11px] w-full h-7 py-0"
                    min={0.1}
                    step={0.1}
                    value={pressureAtm}
                    onChange={(e) => setPressureAtm(e.target.value)}
                  />
                </label>
                <label className="space-y-0.5 block" title="Max lateral dimension mismatch between layers (%). Literature: <3% for crystal-amorphous, <5% for amorphous-amorphous (Lazic 2015, Kubo 2010).">
                  <span className="text-[10px] text-slate-400">XY Tol (%)</span>
                  <input
                    type="number"
                    className="input text-[11px] w-full h-7 py-0"
                    min={0.1}
                    max={50}
                    step={0.5}
                    value={xyTolerance}
                    onChange={(e) => setXyTolerance(e.target.value)}
                  />
                </label>
                <label className="space-y-0.5 block">
                  <span className="text-[10px] text-slate-400">XY/Z Ratio</span>
                  <input
                    type="number"
                    className="input text-[11px] w-full h-7 py-0"
                    min={0.5}
                    step={0.1}
                    value={xyToZRatio}
                    onChange={(e) => setXyToZRatio(e.target.value)}
                  />
                </label>
                <label className="space-y-0.5 block" title="Submit-only vacuum padding in z for slab-corrected electrostatics. Preview geometry is unchanged.">
                  <span className="text-[10px] text-slate-400">Z Vacuum (Å)</span>
                  <input
                    type="number"
                    className="input text-[11px] w-full h-7 py-0"
                    min={0}
                    max={200}
                    step={5}
                    value={zVacuum}
                    onChange={(e) => setZVacuum(e.target.value)}
                  />
                </label>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-1.5 items-start">
            <div className="text-sm text-slate-300 flex flex-col">
              <div className={SECTION_TITLE_CLASS}>Force Field</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-1.5">
                <div className="grid grid-cols-2 gap-1">
                  <button
                    type="button"
                    onClick={() => setFfType('bulk_ff_gaff2')}
                    className={clsx(chipButtonClass(ffType === 'bulk_ff_gaff2', { colorScheme: 'cyan' }), 'px-1 py-1 text-[10px] leading-none')}
                  >
                    GAFF2
                  </button>
                  <button
                    type="button"
                    onClick={() => setFfType('reaxff')}
                    className={clsx(chipButtonClass(ffType === 'reaxff', { colorScheme: 'cyan' }), 'px-1 py-1 text-[10px] leading-none')}
                  >
                    ReaxFF
                  </button>
                </div>
              </div>
            </div>

            <div className="text-sm text-slate-300 flex flex-col">
              <div className={SECTION_TITLE_CLASS}>Boundary</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-1.5 flex items-center gap-1">
                <span className="text-[10px] font-mono text-blue-300">p p f</span>
                <span className="text-[8px] text-slate-500">xy/z</span>
              </div>
            </div>

            <div className="text-sm text-slate-300 flex flex-col">
              <div className={SECTION_TITLE_CLASS}>Seed</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-1.5">
                <input
                  type="number"
                  min={0}
                  step={1}
                  className="input text-xs w-full h-7 py-0"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value)}
                  placeholder="YYYYMMDD"
                />
              </div>
            </div>

            <div className="text-sm text-slate-300 flex flex-col">
              <div className={SECTION_TITLE_CLASS}>E_intra Method</div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-1.5 space-y-1">
                <div className="text-[9px] text-slate-500">Default: {defaultEIntraMethodLabel}</div>
                <select
                  className="input text-[11px] w-full h-7 py-0"
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
                <div className="text-[9px] text-slate-500">Submit: {effectiveEIntraMethodLabel}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Layer Checks (always visible) */}
        <LayerChecksPanel previewData={previewData} />
      </div>

    </>
  )
}

export default LayerSettingsPanel
