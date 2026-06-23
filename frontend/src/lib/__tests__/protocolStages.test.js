import {
  buildEquilibrationSettingsPayload,
  getFallbackStageDefinition,
  getQueueStageLabel,
  getQueueStageVisual,
  getStageSelectionDefault,
  LAYER_CHAIN_KEYS,
  resolveComputedRunTier,
} from '../protocolStages'

describe('protocolStages helpers', () => {
  it('returns a deep-cloned fallback stage definition', () => {
    const first = getFallbackStageDefinition('high_pressure_npt')
    const second = getFallbackStageDefinition('high_pressure_npt')

    first.bounds.temperature_K.min = -1
    first.uiMetadata.parameterFields[0].label = 'Mutated'

    expect(second.bounds.temperature_K.min).toBe(300)
    expect(second.uiMetadata.parameterFields[0].label).toBe('Temperature')
  })

  it('resolves run tier from stage metadata instead of stage-name conditionals', () => {
    const stageConfig = {
      extended_npt: {
        uiMetadata: { submitTier: 'confirm' },
      },
      viscosity_nemd: {
        uiMetadata: { submitTier: 'viscosity' },
      },
    }

    expect(resolveComputedRunTier({ extended_npt: true }, stageConfig)).toBe('confirm')
    expect(
      resolveComputedRunTier(
        { extended_npt: true, viscosity_nemd: true },
        stageConfig
      )
    ).toBe('viscosity')
  })

  it('builds equilibration payloads from metadata mapping', () => {
    const stageConfig = {
      high_temp_nvt: getFallbackStageDefinition('high_temp_nvt'),
      high_pressure_npt: getFallbackStageDefinition('high_pressure_npt'),
    }
    const payload = buildEquilibrationSettingsPayload({
      selectedStages: { high_temp_nvt: true, high_pressure_npt: true },
      stageConfig,
      stageDurations: {
        high_temp_nvt: { ps: 120, steps: null },
        high_pressure_npt: { ps: 240, steps: null },
      },
      stageDefaults: {
        high_temp_nvt: { ps: 100, steps: null },
        high_pressure_npt: { ps: 200, steps: null },
      },
      equilibrationParams: {
        high_temp_nvt: { temperature_K: 550 },
        high_pressure_npt: { temperature_K: 560, pressure_atm: 180 },
      },
    })

    expect(payload).toEqual({
      enabled: true,
      high_temp_nvt_duration_ps: 120,
      high_temp_nvt_temperature_K: 550,
      high_pressure_npt_duration_ps: 240,
      high_pressure_npt_temperature_K: 560,
      high_pressure_npt_pressure_atm: 180,
    })
  })

  describe('getQueueStageLabel', () => {
    it.each([
      ['minimize', 'Minimize'],
      ['high_temp_nvt', 'HT-NVT'],
      ['high_pressure_npt', 'HP-NPT'],
      ['annealing_cycles', 'Anneal'],
      ['nvt_equilibration', 'NVT-eq'],
      ['npt_production', 'NPT'],
      ['npt_equilibration', 'NPT-eq'],
      ['extended_npt', '+NPT'],
      ['viscosity_nemd', 'NEMD'],
      ['tensile_pull', 'Tensile'],
    ])('returns "%s" → "%s"', (stage, expected) => {
      expect(getQueueStageLabel(stage)).toBe(expected)
    })

    it('returns raw stage name for unknown stages', () => {
      expect(getQueueStageLabel('unknown_stage')).toBe('unknown_stage')
    })
  })

  describe('getQueueStageVisual', () => {
    it.each([
      ['minimize', '#94A3B8', 'text-slate-200'],
      ['high_temp_nvt', '#F97316', 'text-orange-200'],
      ['high_pressure_npt', '#EA580C', 'text-orange-200'],
      ['annealing_cycles', '#D97706', 'text-amber-200'],
      ['nvt_equilibration', '#F59E0B', 'text-amber-200'],
      ['npt_production', '#3B82F6', 'text-blue-200'],
      ['npt_equilibration', '#2563EB', 'text-blue-200'],
      ['extended_npt', '#6366F1', 'text-indigo-200'],
      ['viscosity_nemd', '#8B5CF6', 'text-violet-200'],
      ['tensile_pull', '#DC2626', 'text-red-200'],
    ])('returns correct visual for "%s"', (stage, expectedBg, expectedText) => {
      const visual = getQueueStageVisual(stage)
      expect(visual.bg).toBe(expectedBg)
      expect(visual.text).toBe(expectedText)
    })

    it('returns blue fallback for unknown stages', () => {
      const visual = getQueueStageVisual('unknown_stage')
      expect(visual.bg).toBe('#3B82F6')
      expect(visual.text).toBe('text-blue-200')
    })
  })

  describe('getStageSelectionDefault for layer chains', () => {
    it('defaults high_temp_nvt to ON in layer chain (base stage)', () => {
      const cfg = { optional: true }
      expect(getStageSelectionDefault('high_temp_nvt', cfg, ['minimize'], 'layer')).toBe(true)
      expect(getStageSelectionDefault('high_temp_nvt', cfg, ['minimize'], 'tensile_layer')).toBe(true)
    })

    it('defaults optional non-equilibration stage to OFF in non-layer chain', () => {
      const cfg = { optional: true }
      // annealing_cycles is optional and not in EQUILIBRATION_STAGE_KEYS
      expect(getStageSelectionDefault('annealing_cycles', cfg, ['minimize'], 'screening')).toBe(false)
    })

    it('defaults equilibration stage to ON in non-layer chain (coupling)', () => {
      const cfg = { optional: true }
      // high_temp_nvt is in EQUILIBRATION_STAGE_KEYS → always ON in non-layer chains
      expect(getStageSelectionDefault('high_temp_nvt', cfg, ['minimize'], 'screening')).toBe(true)
    })

    it('required stages always ON', () => {
      const cfg = { optional: false }
      expect(getStageSelectionDefault('minimize', cfg, ['minimize'], 'layer')).toBe(true)
    })
  })

  describe('LAYER_CHAIN_KEYS', () => {
    it('contains layer and tensile_layer', () => {
      expect(LAYER_CHAIN_KEYS.has('layer')).toBe(true)
      expect(LAYER_CHAIN_KEYS.has('tensile_layer')).toBe(true)
      expect(LAYER_CHAIN_KEYS.has('screening')).toBe(false)
    })
  })
})
