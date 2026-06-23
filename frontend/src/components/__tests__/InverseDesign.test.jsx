/**
 * Inverse design wizard ①② tests (P4).
 *
 * Pins:
 *   - buildPlanRequest: form state → /inverse-design/plan request body mapping
 *     (custom_targets/temperature/additive explore/interface aggregate_specs/moisture flag)
 *   - TargetPropertiesForm: aggregate section shown for interface targets + submit disabled when none selected
 *   - DesignPlanReview: BOOTSTRAP mode badge/cold-start notice/experiment table/approve button
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { buildPlanRequest } from '../inverse-design/planRequest'
import TargetPropertiesForm from '../inverse-design/TargetPropertiesForm'
import DesignPlanReview from '../inverse-design/DesignPlanReview'

vi.mock('../../api/client', () => ({
  listAdditives: vi.fn().mockResolvedValue({ additives: [] }),
  previewInversePlan: vi.fn(),
  approveInversePlan: vi.fn(),
  getInversePipelineProgress: vi.fn(),
  getInversePipelineResults: vi.fn(),
}))

function withQueryClient(ui) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>
}

const BASE_FORM = {
  targets: [
    { metric_name: 'density', direction: 'maximize', target_min: 1.0, target_max: null },
  ],
  temperatureK: 298,
  aggregates: [],
  binderType: 'AAA1',
  structureSize: 'X1',
  includeAdditive: false,
  additiveType: null,
  moistureDamage: false,
}

describe('buildPlanRequest', () => {
  it('maps bulk targets and temperature', () => {
    const body = buildPlanRequest(BASE_FORM)
    expect(body.custom_targets).toEqual([
      { metric_name: 'density', target_min: 1.0, target_max: null, direction: 'maximize' },
    ])
    expect(body.temperature_k_fixed).toBe(298)
    expect(body.moisture_damage).toBe(false)
    expect(body.aggregate_specs).toBeUndefined()
    expect(body.include_additive).toBeUndefined()
  })

  it('maps binder_type and structure_size (inverse-design decision variables)', () => {
    const body = buildPlanRequest({ ...BASE_FORM, binderType: 'AAK1', structureSize: 'X2' })
    expect(body.binder_types).toEqual(['AAK1'])
    expect(body.structure_size).toBe('X2')
  })

  it('adds aggregate_specs for interface targets', () => {
    const body = buildPlanRequest({
      ...BASE_FORM,
      targets: [
        { metric_name: 'work_of_separation', direction: 'maximize', target_min: 50, target_max: null },
      ],
      aggregates: ['SiO2', 'CaCO3'],
    })
    expect(body.aggregate_specs).toEqual([{ material: 'SiO2' }, { material: 'CaCO3' }])
  })

  it('explores all additives when none picked', () => {
    const body = buildPlanRequest({ ...BASE_FORM, includeAdditive: true, additiveType: null })
    expect(body.include_additive).toBe(true)
    expect(body.explore_all_additives).toBe(true)
  })

  it('fixes additive_type when picked', () => {
    const body = buildPlanRequest({
      ...BASE_FORM,
      includeAdditive: true,
      additiveType: 'SBS_unit',
    })
    expect(body.additive_type).toBe('SBS_unit')
    expect(body.explore_all_additives).toBeUndefined()
  })

  it('carries moisture flag', () => {
    expect(buildPlanRequest({ ...BASE_FORM, moistureDamage: true }).moisture_damage).toBe(true)
  })
})

describe('TargetPropertiesForm', () => {
  it('shows aggregate section only for interface targets', () => {
    const interfaceForm = {
      ...BASE_FORM,
      targets: [
        { metric_name: 'work_of_separation', direction: 'maximize', target_min: 50, target_max: null },
      ],
    }
    const { rerender } = render(
      withQueryClient(
        <TargetPropertiesForm value={BASE_FORM} onChange={() => {}} onSubmit={() => {}} />,
      ),
    )
    expect(screen.queryByText(/Aggregate \(crystal\)/)).toBeNull()

    rerender(
      withQueryClient(
        <TargetPropertiesForm value={interfaceForm} onChange={() => {}} onSubmit={() => {}} />,
      ),
    )
    expect(screen.getByText(/Aggregate \(crystal\)/)).toBeTruthy()
    // No aggregate selected → submit disabled
    expect(screen.getByRole('button', { name: /Preview plan/i }).disabled).toBe(true)
  })

  it('enables submit when targets have bounds', () => {
    render(
      withQueryClient(
        <TargetPropertiesForm value={BASE_FORM} onChange={() => {}} onSubmit={() => {}} />,
      ),
    )
    expect(screen.getByRole('button', { name: /Preview plan/i }).disabled).toBe(false)
  })
})

describe('DesignPlanReview', () => {
  const PLAN = {
    mode: 'bootstrap',
    mode_rationale: { label_starved_targets: ['density'] },
    targets: [
      { metric_name: 'density', target_min: 1.0, target_max: null, unit: 'g/cm3' },
    ],
    candidates: [
      {
        source: 'bootstrap_seed',
        composition: { asphaltene: 15, resin: 30, aromatic: 35, saturate: 20 },
      },
    ],
    experiments: [
      {
        plan_exp_id: 'exp-001',
        kind: 'binder_cell',
        candidate_index: 0,
        temperature_k: 293,
        run_tier: 'screening',
        replicate_seeds: null,
        depends_on: null,
        action: 'build',
      },
    ],
    design: { feasibility: { status: 'unknown', message: '' } },
    moisture_damage: { enabled: false },
  }

  it('renders bootstrap badge, table, and approve action', () => {
    const onApprove = vi.fn()
    render(
      <DesignPlanReview
        plan={PLAN}
        planHash="abc123"
        onApprove={onApprove}
        onBack={() => {}}
      />,
    )
    expect(screen.getByText(/BOOTSTRAP \(DOE seed\)/)).toBeTruthy()
    expect(screen.getByText(/Cold start/)).toBeTruthy()
    expect(screen.getByText('exp-001')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Approve & run/i }))
    expect(onApprove).toHaveBeenCalled()
  })
})
