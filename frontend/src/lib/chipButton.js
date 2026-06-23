import clsx from 'clsx'

const SCHEMES = {
  blue: {
    on: 'bg-blue-500/20 border-blue-500/60 text-blue-300',
    off: 'bg-slate-700/40 border-slate-600 text-slate-300 hover:bg-slate-700',
  },
  cyan: {
    on: 'bg-cyan-500/20 border-cyan-500/60 text-cyan-300',
    off: 'bg-slate-700/40 border-slate-600 text-slate-300 hover:bg-slate-700',
  },
  amber: {
    on: 'bg-amber-500/20 border-amber-500/60 text-amber-300',
    off: 'bg-slate-700/40 border-slate-600 text-slate-300 hover:bg-slate-700',
  },
  // Wave 1: emerald + rose for the new ff_assignment route badges
  // (organic_curated_artifact and ionic_profile, respectively).
  emerald: {
    on: 'bg-emerald-500/20 border-emerald-500/60 text-emerald-300',
    off: 'bg-slate-700/40 border-slate-600 text-slate-300 hover:bg-slate-700',
  },
  rose: {
    on: 'bg-rose-500/20 border-rose-500/60 text-rose-300',
    off: 'bg-slate-700/40 border-slate-600 text-slate-300 hover:bg-slate-700',
  },
}

/**
 * Chip-style toggle button class generator.
 *
 * @param {boolean} active - Whether the chip is selected
 * @param {object} [options]
 * @param {string} [options.colorScheme='blue'] - Color scheme: 'blue' | 'cyan' | 'amber' | 'emerald' | 'rose'
 * @param {string} [options.fontWeight='medium'] - Font weight: 'medium' | 'normal'
 */
export function chipButtonClass(active, { colorScheme = 'blue', fontWeight = 'medium' } = {}) {
  const scheme = SCHEMES[colorScheme] || SCHEMES.blue
  return clsx(
    'px-2 py-1.5 rounded text-xs border transition-colors',
    fontWeight === 'medium' && 'font-medium',
    active ? scheme.on : scheme.off
  )
}
