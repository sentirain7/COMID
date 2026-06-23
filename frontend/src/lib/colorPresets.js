/**
 * Color Preset Definitions — SSOT for all chart/graph colors.
 *
 * Every component that needs SARA, additive, or binder colors MUST import from
 * this module (directly or via constants.js re-export). Inline color definitions
 * are forbidden.
 *
 * New additives that are not in any preset automatically receive a deterministic
 * color via generateAdditiveColor().
 */

const STORAGE_KEY = 'asphalt:color-preset'
const DEFAULT_PRESET = 'gradient_glow'

// ─── Preset Definitions ──────────────────────────────────────────────────────

export const PRESETS = {
  classic: {
    label: 'Classic',
    description: 'Original theme (Tailwind 500)',
    sara: {
      saturate: '#10b981',
      aromatic: '#3b82f6',
      resin: '#f59e0b',
      asphaltene: '#ef4444',
      additive: '#8b5cf6',
    },
    additive: {
      base: '#64748b',
      SBS: '#8b5cf6',
      PPA: '#ec4899',
      Sulfur: '#eab308',
      WMA: '#06b6d4',
      SiO2: '#6366f1',
      Lignin: '#84cc16',
      Elvaloy: '#f97316',
      Sasobit: '#14b8a6',
      NanoClay: '#a855f7',
      CRM: '#78716c',
    },
    binder: {
      AAA1: '#22d3ee',
      AAK1: '#f59e0b',
      AAM1: '#a78bfa',
      custom: '#34d399',
      unknown: '#94a3b8',
    },
    thermo: {
      temperature: '#EF4444',
      pressure: '#3B82F6',
      density: '#22C55E',
      volume: '#F59E0B',
    },
    tier: {
      screening: '#3b82f6',
      confirm: '#8b5cf6',
      viscosity: '#f97316',
      validation: '#ef4444',
    },
    crystal: {
      SiO2: '#60a5fa', CaCO3: '#f59e0b', Al2O3: '#ef4444', MgO: '#34d399',
      Fe2O3: '#f97316', MgCO3: '#a78bfa', CaO: '#ec4899', TiO2: '#06b6d4', ZnO: '#8b5cf6',
    },
    layerType: {
      'interface': '#3b82f6', 'water-interface': '#06b6d4', '3-layer': '#8b5cf6',
      'aged-fresh': '#f59e0b', 'water-aged-fresh': '#14b8a6', 'binder-binder': '#ef4444',
    },
    glow: null,
  },

  vivid_neon: {
    label: 'Vivid Neon',
    description: 'High-saturation neon on dark',
    sara: {
      saturate: '#00e5a0',
      aromatic: '#5b9fff',
      resin: '#ffb930',
      asphaltene: '#ff6b6b',
      additive: '#a78bfa',
    },
    additive: {
      base: '#8899aa',
      SBS: '#a78bfa',
      PPA: '#ff7eb3',
      Sulfur: '#ffe033',
      WMA: '#22e5e5',
      SiO2: '#818cf8',
      Lignin: '#a3e635',
      Elvaloy: '#ff9040',
      Sasobit: '#2dd4bf',
      NanoClay: '#c084fc',
      CRM: '#a8a29e',
    },
    binder: {
      AAA1: '#67e8f9',
      AAK1: '#fbbf24',
      AAM1: '#c4b5fd',
      custom: '#34d399',
      unknown: '#94a3b8',
    },
    thermo: {
      temperature: '#ff6b6b',
      pressure: '#5b9fff',
      density: '#00e5a0',
      volume: '#ffb930',
    },
    tier: {
      screening: '#5b9fff',
      confirm: '#a78bfa',
      viscosity: '#ff9040',
      validation: '#ff6b6b',
    },
    crystal: {
      SiO2: '#5b9fff', CaCO3: '#ffb930', Al2O3: '#ff6b6b', MgO: '#00e5a0',
      Fe2O3: '#ff9040', MgCO3: '#a78bfa', CaO: '#ff7eb3', TiO2: '#22e5e5', ZnO: '#818cf8',
    },
    layerType: {
      'interface': '#5b9fff', 'water-interface': '#22e5e5', '3-layer': '#a78bfa',
      'aged-fresh': '#ffb930', 'water-aged-fresh': '#00e5a0', 'binder-binder': '#ff6b6b',
    },
    glow: { blur: 4, spread: 1, opacity: 0.3 },
  },

  gradient_glow: {
    label: 'Gradient Glow',
    description: 'Tailwind 400 with glow effect',
    sara: {
      saturate: '#34d399',
      aromatic: '#60a5fa',
      resin: '#fbbf24',
      asphaltene: '#f87171',
      additive: '#a78bfa',
    },
    additive: {
      base: '#94a3b8',
      SBS: '#a78bfa',
      PPA: '#f472b6',
      Sulfur: '#facc15',
      WMA: '#22d3ee',
      SiO2: '#818cf8',
      Lignin: '#a3e635',
      Elvaloy: '#fb923c',
      Sasobit: '#2dd4bf',
      NanoClay: '#c084fc',
      CRM: '#a8a29e',
    },
    binder: {
      AAA1: '#67e8f9',
      AAK1: '#fcd34d',
      AAM1: '#c4b5fd',
      custom: '#34d399',
      unknown: '#94a3b8',
    },
    thermo: {
      temperature: '#f87171',
      pressure: '#60a5fa',
      density: '#34d399',
      volume: '#fbbf24',
    },
    tier: {
      screening: '#60a5fa',
      confirm: '#a78bfa',
      viscosity: '#fb923c',
      validation: '#f87171',
    },
    crystal: {
      SiO2: '#60a5fa', CaCO3: '#fbbf24', Al2O3: '#f87171', MgO: '#34d399',
      Fe2O3: '#fb923c', MgCO3: '#a78bfa', CaO: '#f472b6', TiO2: '#22d3ee', ZnO: '#818cf8',
    },
    layerType: {
      'interface': '#60a5fa', 'water-interface': '#22d3ee', '3-layer': '#a78bfa',
      'aged-fresh': '#fbbf24', 'water-aged-fresh': '#34d399', 'binder-binder': '#f87171',
    },
    glow: { blur: 6, spread: 1, opacity: 0.4 },
  },

  pastel_bright: {
    label: 'Pastel Bright',
    description: 'Soft pastel (Tailwind 200-300)',
    sara: {
      saturate: '#6ee7b7',
      aromatic: '#93c5fd',
      resin: '#fcd34d',
      asphaltene: '#fca5a5',
      additive: '#c4b5fd',
    },
    additive: {
      base: '#cbd5e1',
      SBS: '#c4b5fd',
      PPA: '#f9a8d4',
      Sulfur: '#fde68a',
      WMA: '#67e8f9',
      SiO2: '#a5b4fc',
      Lignin: '#bef264',
      Elvaloy: '#fdba74',
      Sasobit: '#5eead4',
      NanoClay: '#d8b4fe',
      CRM: '#d6d3d1',
    },
    binder: {
      AAA1: '#a5f3fc',
      AAK1: '#fde68a',
      AAM1: '#ddd6fe',
      custom: '#34d399',
      unknown: '#94a3b8',
    },
    thermo: {
      temperature: '#fca5a5',
      pressure: '#93c5fd',
      density: '#6ee7b7',
      volume: '#fcd34d',
    },
    tier: {
      screening: '#93c5fd',
      confirm: '#c4b5fd',
      viscosity: '#fdba74',
      validation: '#fca5a5',
    },
    crystal: {
      SiO2: '#93c5fd', CaCO3: '#fde68a', Al2O3: '#fca5a5', MgO: '#6ee7b7',
      Fe2O3: '#fdba74', MgCO3: '#c4b5fd', CaO: '#f9a8d4', TiO2: '#67e8f9', ZnO: '#a5b4fc',
    },
    layerType: {
      'interface': '#93c5fd', 'water-interface': '#67e8f9', '3-layer': '#c4b5fd',
      'aged-fresh': '#fde68a', 'water-aged-fresh': '#6ee7b7', 'binder-binder': '#fca5a5',
    },
    glow: { blur: 5, spread: 1, opacity: 0.25 },
  },
}

// ─── Analysis Background Presets ─────────────────────────────────────────────
//
// Each background preset bundles container styling AND optimised foreground
// colors so the combination guarantees readability.

const ANALYSIS_BG_STORAGE_KEY = 'asphalt:analysis-bg'
const DEFAULT_ANALYSIS_BG = 'obsidian'

export const ANALYSIS_BG_PRESETS = {
  obsidian: {
    label: 'Obsidian',
    description: 'Blue-gray dark — high-contrast accents',
    bg: {
      container: '#0d1117',
      containerAlpha: 'rgba(13, 17, 23, 0.55)',
      card: '#161b22',
      cardAlpha: 'rgba(22, 27, 34, 0.95)',
      border: '#30363d',
      grid: '#30363d',
      gridSub: '#21262d',
      text: '#f0f6fc',
      textMuted: '#8b949e',
      overlay: 'rgba(13, 17, 23, 0.85)',
    },
    sara: {
      saturate: '#3fb950',
      aromatic: '#58a6ff',
      resin: '#d29922',
      asphaltene: '#f85149',
      additive: '#bc8cff',
    },
    additive: {
      base: '#8b949e',
      SBS: '#bc8cff',
      PPA: '#f778ba',
      Sulfur: '#e3b341',
      WMA: '#39d2c0',
      SiO2: '#79c0ff',
      Lignin: '#7ee787',
      Elvaloy: '#ffa657',
      Sasobit: '#56d4dd',
      NanoClay: '#d2a8ff',
      CRM: '#a5a5a5',
    },
    binder: {
      AAA1: '#79c0ff',
      AAK1: '#e3b341',
      AAM1: '#d2a8ff',
      custom: '#56d4dd',
      unknown: '#8b949e',
    },
    crystal: {
      SiO2: '#58a6ff', CaCO3: '#d29922', Al2O3: '#f85149', MgO: '#3fb950',
      Fe2O3: '#ffa657', MgCO3: '#bc8cff', CaO: '#f778ba', TiO2: '#39d2c0', ZnO: '#79c0ff',
    },
    layerType: {
      'interface': '#58a6ff', 'water-interface': '#39d2c0', '3-layer': '#bc8cff',
      'aged-fresh': '#d29922', 'water-aged-fresh': '#3fb950', 'binder-binder': '#f85149',
    },
  },

  deep_ocean: {
    label: 'Deep Ocean',
    description: 'Navy blue — warm accents pop on cool depth',
    bg: {
      container: '#06101f',
      containerAlpha: 'rgba(6, 16, 31, 0.6)',
      card: '#0b1a2e',
      cardAlpha: 'rgba(11, 26, 46, 0.95)',
      border: '#1a3050',
      grid: '#1a3050',
      gridSub: '#0f2340',
      text: '#dce8f5',
      textMuted: '#6e8eaf',
      overlay: 'rgba(6, 16, 31, 0.88)',
    },
    sara: {
      saturate: '#4ade80',
      aromatic: '#7dd3fc',
      resin: '#fbbf24',
      asphaltene: '#fb7185',
      additive: '#c084fc',
    },
    additive: {
      base: '#7daec4',
      SBS: '#c084fc',
      PPA: '#fb7185',
      Sulfur: '#fcd34d',
      WMA: '#5eead4',
      SiO2: '#a5b4fc',
      Lignin: '#86efac',
      Elvaloy: '#fdba74',
      Sasobit: '#67e8f9',
      NanoClay: '#d8b4fe',
      CRM: '#b0b8c4',
    },
    binder: {
      AAA1: '#67e8f9',
      AAK1: '#fbbf24',
      AAM1: '#d8b4fe',
      custom: '#5eead4',
      unknown: '#7daec4',
    },
    crystal: {
      SiO2: '#7dd3fc', CaCO3: '#fbbf24', Al2O3: '#fb7185', MgO: '#4ade80',
      Fe2O3: '#fdba74', MgCO3: '#c084fc', CaO: '#f9a8d4', TiO2: '#5eead4', ZnO: '#a5b4fc',
    },
    layerType: {
      'interface': '#7dd3fc', 'water-interface': '#5eead4', '3-layer': '#c084fc',
      'aged-fresh': '#fbbf24', 'water-aged-fresh': '#4ade80', 'binder-binder': '#fb7185',
    },
  },

  warm_graphite: {
    label: 'Warm Graphite',
    description: 'Neutral warm dark — balanced saturation',
    bg: {
      container: '#161418',
      containerAlpha: 'rgba(22, 20, 24, 0.55)',
      card: '#201e24',
      cardAlpha: 'rgba(32, 30, 36, 0.95)',
      border: '#3a3640',
      grid: '#3a3640',
      gridSub: '#2a2830',
      text: '#eae8ee',
      textMuted: '#9a96a4',
      overlay: 'rgba(22, 20, 24, 0.88)',
    },
    sara: {
      saturate: '#2dd4bf',
      aromatic: '#60a5fa',
      resin: '#fbbf24',
      asphaltene: '#fb923c',
      additive: '#a78bfa',
    },
    additive: {
      base: '#9a96a4',
      SBS: '#a78bfa',
      PPA: '#f472b6',
      Sulfur: '#facc15',
      WMA: '#22d3ee',
      SiO2: '#818cf8',
      Lignin: '#a3e635',
      Elvaloy: '#fb923c',
      Sasobit: '#2dd4bf',
      NanoClay: '#c084fc',
      CRM: '#b8b4be',
    },
    binder: {
      AAA1: '#67e8f9',
      AAK1: '#fcd34d',
      AAM1: '#c4b5fd',
      custom: '#2dd4bf',
      unknown: '#9a96a4',
    },
    crystal: {
      SiO2: '#60a5fa', CaCO3: '#fbbf24', Al2O3: '#fb923c', MgO: '#2dd4bf',
      Fe2O3: '#fb923c', MgCO3: '#a78bfa', CaO: '#f472b6', TiO2: '#22d3ee', ZnO: '#818cf8',
    },
    layerType: {
      'interface': '#60a5fa', 'water-interface': '#22d3ee', '3-layer': '#a78bfa',
      'aged-fresh': '#fbbf24', 'water-aged-fresh': '#2dd4bf', 'binder-binder': '#fb923c',
    },
  },
}

// ─── Active Preset ───────────────────────────────────────────────────────────

export function getActivePresetName() {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_PRESET
  } catch {
    return DEFAULT_PRESET
  }
}

function resolvePreset(name) {
  return PRESETS[name] || PRESETS[DEFAULT_PRESET]
}

const _active = resolvePreset(getActivePresetName())

/** Mutable export — updated in-place by setColorPreset(). */
export const SARA_COLORS = { ..._active.sara }
/** Mutable export — updated in-place by setColorPreset(). */
export const ADDITIVE_COLORS = { ..._active.additive }
/** Mutable export — updated in-place by setColorPreset(). */
export const BINDER_COLORS = { ..._active.binder }
/** Mutable export — updated in-place by setColorPreset(). */
export const THERMO_COLORS = { ..._active.thermo }
/** Mutable export — updated in-place by setColorPreset(). */
export const TIER_COLORS = { ..._active.tier }
/** Mutable export — updated in-place by setColorPreset(). */
export const CRYSTAL_COLORS = { ...(_active.crystal || {}) }
/** Mutable export — updated in-place by setColorPreset(). */
export const LAYER_TYPE_COLORS = { ...(_active.layerType || {}) }

// ─── Preset Switching ────────────────────────────────────────────────────────

/**
 * Switch the active color preset.
 *
 * Updates localStorage and mutates the module-level SARA_COLORS, ADDITIVE_COLORS,
 * BINDER_COLORS objects in-place so all existing references reflect the change.
 */
export function setColorPreset(name) {
  const preset = resolvePreset(name)
  try {
    localStorage.setItem(STORAGE_KEY, name)
  } catch {
    // SSR / incognito — ignore
  }

  // Clear and reassign to handle keys that only exist in some presets
  for (const key of Object.keys(SARA_COLORS)) delete SARA_COLORS[key]
  Object.assign(SARA_COLORS, preset.sara)

  for (const key of Object.keys(ADDITIVE_COLORS)) delete ADDITIVE_COLORS[key]
  Object.assign(ADDITIVE_COLORS, preset.additive)

  for (const key of Object.keys(BINDER_COLORS)) delete BINDER_COLORS[key]
  Object.assign(BINDER_COLORS, preset.binder)

  for (const key of Object.keys(THERMO_COLORS)) delete THERMO_COLORS[key]
  Object.assign(THERMO_COLORS, preset.thermo)

  for (const key of Object.keys(TIER_COLORS)) delete TIER_COLORS[key]
  Object.assign(TIER_COLORS, preset.tier)

  for (const key of Object.keys(CRYSTAL_COLORS)) delete CRYSTAL_COLORS[key]
  Object.assign(CRYSTAL_COLORS, preset.crystal || {})

  for (const key of Object.keys(LAYER_TYPE_COLORS)) delete LAYER_TYPE_COLORS[key]
  Object.assign(LAYER_TYPE_COLORS, preset.layerType || {})

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('asphalt:theme-change', { detail: { scope: 'chart', preset: name } }))
  }
}

// ─── Analysis Background ─────────────────────────────────────────────────────

export function getActiveAnalysisBgName() {
  try {
    return localStorage.getItem(ANALYSIS_BG_STORAGE_KEY) || DEFAULT_ANALYSIS_BG
  } catch {
    return DEFAULT_ANALYSIS_BG
  }
}

function resolveAnalysisBg(name) {
  return ANALYSIS_BG_PRESETS[name] || ANALYSIS_BG_PRESETS[DEFAULT_ANALYSIS_BG]
}

const _activeBg = resolveAnalysisBg(getActiveAnalysisBgName())

/** Mutable export — updated in-place by setAnalysisBg(). */
export const ANALYSIS_BG = { ..._activeBg.bg }
/** Mutable export — analysis-specific SARA colors optimised for the active background. */
export const ANALYSIS_SARA = { ..._activeBg.sara }
/** Mutable export — analysis-specific additive colors optimised for the active background. */
export const ANALYSIS_ADDITIVE = { ..._activeBg.additive }
/** Mutable export — analysis-specific binder colors optimised for the active background. */
export const ANALYSIS_BINDER = { ..._activeBg.binder }
/** Mutable export — analysis-specific crystal material colors optimised for the active background. */
export const ANALYSIS_CRYSTAL = { ...(_activeBg.crystal || {}) }
/** Mutable export — analysis-specific layer-type colors optimised for the active background. */
export const ANALYSIS_LAYER_TYPE = { ...(_activeBg.layerType || {}) }

/**
 * Switch the analysis background preset.
 *
 * Updates localStorage and mutates ANALYSIS_BG, ANALYSIS_SARA,
 * ANALYSIS_ADDITIVE, ANALYSIS_BINDER in-place.
 */
export function setAnalysisBg(name) {
  const preset = resolveAnalysisBg(name)
  try {
    localStorage.setItem(ANALYSIS_BG_STORAGE_KEY, name)
  } catch {
    // SSR / incognito — ignore
  }

  for (const key of Object.keys(ANALYSIS_BG)) delete ANALYSIS_BG[key]
  Object.assign(ANALYSIS_BG, preset.bg)

  for (const key of Object.keys(ANALYSIS_SARA)) delete ANALYSIS_SARA[key]
  Object.assign(ANALYSIS_SARA, preset.sara)

  for (const key of Object.keys(ANALYSIS_ADDITIVE)) delete ANALYSIS_ADDITIVE[key]
  Object.assign(ANALYSIS_ADDITIVE, preset.additive)

  for (const key of Object.keys(ANALYSIS_BINDER)) delete ANALYSIS_BINDER[key]
  Object.assign(ANALYSIS_BINDER, preset.binder)

  for (const key of Object.keys(ANALYSIS_CRYSTAL)) delete ANALYSIS_CRYSTAL[key]
  Object.assign(ANALYSIS_CRYSTAL, preset.crystal || {})

  for (const key of Object.keys(ANALYSIS_LAYER_TYPE)) delete ANALYSIS_LAYER_TYPE[key]
  Object.assign(ANALYSIS_LAYER_TYPE, preset.layerType || {})

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('asphalt:theme-change', { detail: { scope: 'analysis', preset: name } }))
  }
}

/**
 * Resolve the display color for an additive in the Analysis context.
 *
 * Uses ANALYSIS_ADDITIVE (optimised for the selected background), with
 * fallback to generateAdditiveColor() for unknown additives.
 */
export function getAnalysisAdditiveColor(additive) {
  if (!additive || additive === 'None' || additive === 'none') return ANALYSIS_ADDITIVE.base
  return ANALYSIS_ADDITIVE[additive] || generateAdditiveColor(additive)
}

/**
 * Resolve the display color for a crystal material in the Analysis context.
 */
export function getAnalysisCrystalColor(material) {
  if (!material) return ANALYSIS_CRYSTAL.SiO2 || '#60a5fa'
  return ANALYSIS_CRYSTAL[material] || generateAdditiveColor(material)
}

/**
 * Resolve the display color for a layer type in the Analysis context.
 */
export function getAnalysisLayerTypeColor(layerType) {
  if (!layerType) return ANALYSIS_LAYER_TYPE.interface || '#3b82f6'
  return ANALYSIS_LAYER_TYPE[layerType] || generateAdditiveColor(layerType)
}

// ─── Glow Configuration ──────────────────────────────────────────────────────

/**
 * Return the glow config for the active preset, or null if glow is disabled.
 *
 * @returns {{ blur: number, spread: number, opacity: number } | null}
 */
export function getGlowConfig() {
  return resolvePreset(getActivePresetName()).glow
}

// ─── Dynamic Additive Color ──────────────────────────────────────────────────

/**
 * Convert HSL values to a hex color string.
 * @param {number} h - Hue (0-360)
 * @param {number} s - Saturation (0-100)
 * @param {number} l - Lightness (0-100)
 * @returns {string} Hex color string (e.g. "#34d399")
 */
function hslToHex(h, s, l) {
  s /= 100
  l /= 100
  const a = s * Math.min(l, 1 - l)
  const f = (n) => {
    const k = (n + h / 30) % 12
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1)
    return Math.round(255 * color).toString(16).padStart(2, '0')
  }
  return `#${f(0)}${f(8)}${f(4)}`
}

/**
 * Generate a deterministic, visually distinct hex color for an unknown additive.
 *
 * Uses a hash of the name to produce a bright, saturated color that is
 * legible on dark (slate-800) backgrounds.
 *
 * @param {string} name - Additive name or mol_id
 * @returns {string} Hex color string
 */
export function generateAdditiveColor(name) {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  const hue = ((hash % 360) + 360) % 360
  const sat = 65 + Math.abs((hash >> 8) % 20) // 65-85%
  const lit = 55 + Math.abs((hash >> 16) % 15) // 55-70%
  return hslToHex(hue, sat, lit)
}
