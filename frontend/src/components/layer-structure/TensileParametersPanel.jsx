import { SECTION_TITLE_CLASS } from './config'

function TensileParametersPanel({
  tensilePullVelocity,
  setTensilePullVelocity,
  tensileGripThickness,
  setTensileGripThickness,
  tensileMaxStrain,
  setTensileMaxStrain,
}) {
  return (
    <div className="text-sm text-slate-300 flex flex-col">
      <div className={SECTION_TITLE_CLASS}>Tensile Parameters</div>
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2">
        <div className="grid grid-cols-3 gap-2">
          <label className="space-y-0.5 block">
            <span className="text-[10px] text-slate-400">
              Pull Velocity (Å/fs)
            </span>
            <input
              type="number"
              className="input text-xs w-full"
              min={0.000001}
              max={0.01}
              step={0.00001}
              value={tensilePullVelocity}
              onChange={(e) => setTensilePullVelocity(e.target.value)}
            />
            <div className="text-[9px] text-slate-500">
              ≈ {(Number(tensilePullVelocity) * 1e5).toFixed(1)} m/s
            </div>
          </label>
          <label className="space-y-0.5 block">
            <span className="text-[10px] text-slate-400">
              Grip Thickness (Å)
            </span>
            <input
              type="number"
              className="input text-xs w-full"
              min={5}
              max={100}
              step={1}
              value={tensileGripThickness}
              onChange={(e) => setTensileGripThickness(e.target.value)}
            />
          </label>
          <label className="space-y-0.5 block">
            <span className="text-[10px] text-slate-400">
              Max Strain
            </span>
            <input
              type="number"
              className="input text-xs w-full"
              min={0.1}
              max={2.0}
              step={0.1}
              value={tensileMaxStrain}
              onChange={(e) => setTensileMaxStrain(e.target.value)}
            />
          </label>
        </div>
      </div>
    </div>
  )
}

export default TensileParametersPanel
