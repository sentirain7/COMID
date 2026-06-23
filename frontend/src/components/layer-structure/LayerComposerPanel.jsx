import clsx from 'clsx'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { PRESET_MATERIAL_OPTIONS } from '../crystal-structures/config'
import { SOURCE_TYPE_OPTIONS, SECTION_TITLE_CLASS, XY_WARN_PCT, XY_FAIL_PCT } from './config'
import { renderSourceLabel } from './helpers'

function LayerComposerPanel({
  layers,
  sourceCatalog,
  layerXYErrors,
  interLayerGap,
  setInterLayerGap,
  canAddLayer,
  canRemoveLayer,
  addLayer,
  removeLayer,
  moveLayer,
  handleLayerField,
  // preview/submit buttons
  previewMutation,
  submitMutation,
  handlePreview,
  handleSubmit,
}) {
  return (
    <div className="text-sm text-slate-300 flex flex-col">
      <div className={clsx(SECTION_TITLE_CLASS, 'flex items-center justify-between gap-2')}>
        <span>Layer Composer</span>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <button
            type="button"
            className={clsx(
              'px-2 py-1 rounded text-xs font-medium',
              canAddLayer
                ? 'bg-blue-500/20 text-blue-300 hover:bg-blue-500/30'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed'
            )}
            onClick={addLayer}
            disabled={!canAddLayer}
          >
            <Plus className="w-3.5 h-3.5 inline mr-1" />
            Add Layer
          </button>
          <button
            type="button"
            className={clsx(
              'px-3 py-2 rounded text-xs font-medium',
              previewMutation.isPending
                ? 'bg-slate-700 text-slate-300 cursor-not-allowed'
                : 'bg-blue-500/20 text-blue-300 hover:bg-blue-500/30'
            )}
            disabled={previewMutation.isPending}
            onClick={handlePreview}
          >
            {previewMutation.isPending ? 'Previewing...' : 'Preview Stack'}
          </button>
          <button
            type="button"
            className={clsx(
              'px-3 py-2 rounded text-xs font-medium',
              submitMutation.isPending
                ? 'bg-slate-700 text-slate-300 cursor-not-allowed'
                : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'
            )}
            disabled={submitMutation.isPending}
            onClick={handleSubmit}
          >
            {submitMutation.isPending ? 'Submitting...' : 'Submit'}
          </button>
        </div>
      </div>
      {/* Top-down display: highest z at visual top, Layer 1 (z=0) at visual bottom.
          Matches 3D preview (zUp) so the composer reads like the physical stack. */}
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 space-y-1.5">
        <div className="flex items-center gap-2 text-[10px] text-slate-400 mb-1.5">
          <span>Default gap:</span>
          <input type="number" className="input text-[10px] w-14 h-5 px-1 py-0 text-center"
            min={0} max={20} step={0.5}
            value={interLayerGap}
            onChange={(e) => setInterLayerGap(e.target.value)}
          />
          <span>Å</span>
          <span className="text-slate-500 ml-1">(per-layer override →)</span>
        </div>
        {[...layers].reverse().map((row) => {
          const dataIndex = layers.indexOf(row)
          const options = sourceCatalog[row.sourceType] || []
          const isTopLayer = dataIndex === layers.length - 1
          const isBottomLayer = dataIndex === 0
          return (
            <div key={row.rowId} className="rounded border border-slate-700/80 bg-slate-900/30 p-1.5">
              <div className="grid grid-cols-1 sm:grid-cols-[70px_1fr_1.7fr_auto] gap-2 items-center">
                <div className="text-xs text-slate-300 font-medium flex items-center gap-1">
                  <span>Layer {dataIndex + 1}</span>
                  {isTopLayer && <span className="text-[9px] text-slate-500">(top)</span>}
                  {isBottomLayer && <span className="text-[9px] text-slate-500">(btm)</span>}
                </div>
                <select
                  className="input text-xs"
                  value={row.sourceType}
                  onChange={(e) => handleLayerField(row.rowId, 'sourceType', e.target.value)}
                >
                  {SOURCE_TYPE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>

                {row.sourceType === 'crystal_structure' && row.autoMatchMaterial ? (
                  <div className="flex items-center gap-1.5">
                    <select
                      className="input text-xs flex-1"
                      value={row.autoMatchMaterial}
                      onChange={(e) => handleLayerField(row.rowId, 'autoMatchMaterial', e.target.value)}
                    >
                      <option value="">Auto-match material...</option>
                      {PRESET_MATERIAL_OPTIONS.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="text-[9px] text-slate-400 hover:text-slate-200 whitespace-nowrap"
                      onClick={() => handleLayerField(row.rowId, 'autoMatchMaterial', '')}
                      title="Switch to manual crystal selection"
                    >manual</button>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <select
                      className="input text-xs flex-1"
                      value={row.sourceId}
                      onChange={(e) => handleLayerField(row.rowId, 'sourceId', e.target.value)}
                    >
                      <option value="">Select source...</option>
                      {options.map((item) => (
                        <option key={item.source_id} value={item.source_id}>
                          {renderSourceLabel(item)}
                        </option>
                      ))}
                    </select>
                    {row.sourceType === 'crystal_structure' && (
                      row.autoSelected ? (
                        <span
                          className="text-[9px] text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded whitespace-nowrap"
                          title="Auto-selected to match adjacent layer XY size"
                        >changed</span>
                      ) : (
                        <button
                          type="button"
                          className="text-[9px] text-blue-400 hover:text-blue-300 whitespace-nowrap"
                          onClick={() => handleLayerField(row.rowId, 'autoMatchMaterial', 'SiO2')}
                          title="Auto-match crystal by material (best XY match)"
                        >auto</button>
                      )
                    )}
                  </div>
                )}

                <div className="flex items-center justify-end gap-1">
                  {(() => {
                    const xyErr = layerXYErrors.get(row.rowId)
                    if (!xyErr) return null
                    const pct = xyErr.errorPct
                    const status = pct <= XY_WARN_PCT ? 'pass' : pct <= XY_FAIL_PCT ? 'warn' : 'fail'
                    const tone = status === 'pass' ? 'text-emerald-400' : status === 'warn' ? 'text-amber-400' : 'text-red-400'
                    const bg = status === 'pass' ? '' : status === 'warn' ? 'bg-amber-500/10' : 'bg-red-500/10'
                    return (
                      <span
                        className={`text-[9px] ${tone} ${bg} px-1 rounded whitespace-nowrap`}
                        title={`This: ${xyErr.thisXY[0].toFixed(1)}×${xyErr.thisXY[1].toFixed(1)} Å | Ref: ${xyErr.refXY[0].toFixed(1)}×${xyErr.refXY[1].toFixed(1)} Å\nPass ≤${XY_WARN_PCT}% | Warn ≤${XY_FAIL_PCT}% | Fail >${XY_FAIL_PCT}%`}
                      >
                        ΔXY {pct.toFixed(1)}%
                      </span>
                    )
                  })()}
                  <label
                    className="flex items-center gap-0.5 text-[10px] text-slate-400"
                    title={!isTopLayer ? 'Gap above this layer (Å). Empty = use default.' : 'Top layer has no gap above.'}
                  >
                    <span>Gap</span>
                    <input
                      type="number"
                      className={clsx(
                        'input text-[10px] w-12 h-6 px-1 py-0 text-center',
                        isTopLayer && 'opacity-50 cursor-not-allowed'
                      )}
                      min={0}
                      max={20}
                      step={0.5}
                      value={!isTopLayer ? row.gapAfter : 0}
                      placeholder={!isTopLayer ? String(interLayerGap) : '0'}
                      disabled={isTopLayer}
                      onChange={(e) => handleLayerField(row.rowId, 'gapAfter', e.target.value)}
                    />
                    <span>Å</span>
                  </label>
                  <button
                    type="button"
                    className="p-1 rounded bg-slate-700/70 text-slate-200 hover:bg-slate-700"
                    onClick={() => moveLayer(dataIndex, 1)}
                    disabled={isTopLayer}
                    title="Move up (higher z)"
                  >
                    <ArrowUp className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    className="p-1 rounded bg-slate-700/70 text-slate-200 hover:bg-slate-700"
                    onClick={() => moveLayer(dataIndex, -1)}
                    disabled={isBottomLayer}
                    title="Move down (lower z)"
                  >
                    <ArrowDown className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    className={clsx(
                      'p-1 rounded',
                      canRemoveLayer
                        ? 'bg-red-500/15 text-red-300 hover:bg-red-500/25'
                        : 'bg-slate-700 text-slate-500 cursor-not-allowed'
                    )}
                    onClick={() => removeLayer(row.rowId)}
                    disabled={!canRemoveLayer}
                    title="Remove layer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default LayerComposerPanel
