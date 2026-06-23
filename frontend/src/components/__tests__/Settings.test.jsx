import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock the hooks barrel so Settings can import them
vi.mock('../../hooks/useApi', () => ({
  useSettings: vi.fn(() => ({
    settings: {
      gpu_enabled: true,
      selected_gpus: [],
      llm_provider: 'mock',
      max_concurrent_jobs: 4,
      default_tier: 'screening',
      auto_retry_on_failure: true,
      refresh_interval_queue_ms: 3000,
      refresh_interval_gpu_ms: 3000,
      refresh_interval_system_ms: 5000,
      default_e_intra_method: 'single_molecule_vacuum_adaptive_cutoff',
    },
    loading: false,
    error: null,
    update: vi.fn(),
  })),
  useGPUStats: vi.fn(() => ({
    data: {
      gpus: [
        { id: 0, name: 'NVIDIA H100', status: 'available', utilization: 15 },
        { id: 1, name: 'NVIDIA H100', status: 'busy', utilization: 92 },
      ],
    },
  })),
}))

// Mock colorPresets so we don't need localStorage
vi.mock('../../lib/colorPresets', () => ({
  getActivePresetName: () => 'gradient_glow',
  getActiveAnalysisBgName: () => 'obsidian',
  setColorPreset: vi.fn(),
  setAnalysisBg: vi.fn(),
  PRESETS: {
    gradient_glow: {
      label: 'Gradient Glow',
      description: 'Tailwind 400 with glow effect',
      sara: { saturate: '#34d399', aromatic: '#60a5fa', resin: '#fbbf24', asphaltene: '#f87171' },
      glow: { blur: 6, spread: 1, opacity: 0.4 },
    },
    classic: {
      label: 'Classic',
      description: 'Original theme',
      sara: { saturate: '#10b981', aromatic: '#3b82f6', resin: '#f59e0b', asphaltene: '#ef4444' },
      glow: null,
    },
  },
  ANALYSIS_BG_PRESETS: {
    obsidian: {
      label: 'Obsidian',
      description: 'Blue-gray dark',
      bg: { container: '#0d1117', card: '#161b22', border: '#30363d', grid: '#30363d', text: '#f0f6fc', textMuted: '#8b949e' },
      sara: { saturate: '#3fb950', aromatic: '#58a6ff', resin: '#d29922', asphaltene: '#f85149' },
    },
  },
  SARA_COLORS: {},
  ADDITIVE_COLORS: {},
  BINDER_COLORS: {},
  THERMO_COLORS: {},
  TIER_COLORS: {},
  CRYSTAL_COLORS: {},
  LAYER_TYPE_COLORS: {},
  ANALYSIS_BG: {},
  ANALYSIS_SARA: {},
  ANALYSIS_ADDITIVE: {},
  ANALYSIS_BINDER: {},
  ANALYSIS_CRYSTAL: {},
  ANALYSIS_LAYER_TYPE: {},
}))

import Settings from '../Settings'

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Rendering ───────────────────────────────────────────────────────────────

describe('Settings', () => {
  it('renders without crashing', () => {
    render(<Settings />)
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('shows theme section with color preset options', () => {
    render(<Settings />)
    expect(screen.getByText('Appearance')).toBeInTheDocument()
    expect(screen.getByText('Chart Color Preset')).toBeInTheDocument()
    expect(screen.getByText('Gradient Glow')).toBeInTheDocument()
    expect(screen.getByText('Classic')).toBeInTheDocument()
  })

  it('renders GPU section', () => {
    render(<Settings />)
    expect(screen.getByText('GPU Configuration')).toBeInTheDocument()
    expect(screen.getByText('Enable GPU Acceleration')).toBeInTheDocument()
    expect(screen.getByText('GPU Selection')).toBeInTheDocument()
    // GPU cards
    expect(screen.getByText('GPU 0')).toBeInTheDocument()
    expect(screen.getByText('GPU 1')).toBeInTheDocument()
  })

  it('renders LLM provider section', () => {
    render(<Settings />)
    expect(screen.getByRole('heading', { name: 'LLM Provider' })).toBeInTheDocument()
  })

  it('renders refresh intervals section', () => {
    render(<Settings />)
    // Simulation Defaults section was removed (dead settings with no runtime
    // effect: max_concurrent_jobs / default_tier / auto_retry_on_failure).
    expect(screen.queryByText('Simulation Defaults')).not.toBeInTheDocument()
    expect(screen.getByText('Refresh Intervals')).toBeInTheDocument()
    expect(screen.getByText('Queue Stats Refresh')).toBeInTheDocument()
  })

  it('renders E_intra defaults section', () => {
    render(<Settings />)
    expect(screen.getByText('E_intra Defaults')).toBeInTheDocument()
    expect(screen.getByLabelText('Default E_intra Method')).toBeInTheDocument()
    expect(screen.getByText(/Current default: Vacuum Adaptive/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Default E_intra Method')).not.toHaveTextContent(
      'Periodic PPPM',
    )
  })

  it('shows info note about session settings', () => {
    render(<Settings />)
    expect(screen.getByText('Session Settings')).toBeInTheDocument()
  })
})
