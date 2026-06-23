import clsx from 'clsx'
import { Palette } from 'lucide-react'
import {
  PRESETS,
  setColorPreset,
  ANALYSIS_BG_PRESETS,
  setAnalysisBg,
} from '../../lib/colorPresets'

function ThemeSection({
  activePreset,
  setActivePreset,
  activeAnalysisBg,
  setActiveAnalysisBg,
}) {
  return (
    <section className="card">
      <div className="card-header flex items-center gap-2">
        <Palette className="w-5 h-5 text-slate-400" />
        <h2 className="text-lg font-semibold text-white">Appearance</h2>
      </div>
      <div className="card-body space-y-4">
        <div>
          <label className="text-white font-medium">Chart Color Preset</label>
          <p className="text-sm text-slate-400 mt-1">
            Choose a color scheme for analysis charts and data points.
            Changes apply when navigating to chart pages.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(PRESETS).map(([key, preset]) => (
            <button
              key={key}
              type="button"
              onClick={() => {
                setColorPreset(key)
                setActivePreset(key)
              }}
              className={clsx(
                'p-3 rounded-lg border text-left transition-colors',
                activePreset === key
                  ? 'bg-blue-500/20 border-blue-500/50'
                  : 'bg-slate-700/50 border-slate-600 hover:border-slate-500'
              )}
            >
              <div className="text-sm font-medium text-white">{preset.label}</div>
              <div className="text-xs text-slate-400 mt-1">{preset.description}</div>
              <div className="flex gap-1.5 mt-2">
                {Object.values(preset.sara).map((color, i) => (
                  <div
                    key={i}
                    className="w-4 h-4 rounded-full"
                    style={{
                      backgroundColor: color,
                      boxShadow: preset.glow
                        ? `0 0 ${preset.glow.blur}px ${preset.glow.spread}px ${color}${Math.round(preset.glow.opacity * 255).toString(16).padStart(2, '0')}`
                        : 'none',
                    }}
                  />
                ))}
              </div>
            </button>
          ))}
        </div>

        {/* Analysis Background */}
        <div className="border-t border-slate-700 pt-4 mt-4">
          <label className="text-white font-medium">Analysis Background</label>
          <p className="text-sm text-slate-400 mt-1">
            Choose a background theme for the Analysis page.
            Each theme bundles background + optimised chart colors for readability.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {Object.entries(ANALYSIS_BG_PRESETS).map(([key, preset]) => (
            <button
              key={key}
              type="button"
              onClick={() => {
                setAnalysisBg(key)
                setActiveAnalysisBg(key)
              }}
              className={clsx(
                'p-3 rounded-lg border text-left transition-colors',
                activeAnalysisBg === key
                  ? 'border-blue-500/50'
                  : 'border-slate-600 hover:border-slate-500'
              )}
              style={{ backgroundColor: preset.bg.container }}
            >
              <div className="text-sm font-medium" style={{ color: preset.bg.text }}>{preset.label}</div>
              <div className="text-xs mt-1" style={{ color: preset.bg.textMuted }}>{preset.description}</div>
              <div className="flex gap-1.5 mt-2">
                {Object.values(preset.sara).map((color, i) => (
                  <div
                    key={i}
                    className="w-4 h-4 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                ))}
              </div>
              <div className="flex gap-1 mt-1.5">
                <div className="h-1.5 flex-1 rounded-full" style={{ backgroundColor: preset.bg.card }} />
                <div className="h-1.5 flex-1 rounded-full" style={{ backgroundColor: preset.bg.border }} />
                <div className="h-1.5 flex-1 rounded-full" style={{ backgroundColor: preset.bg.grid }} />
              </div>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

export default ThemeSection
