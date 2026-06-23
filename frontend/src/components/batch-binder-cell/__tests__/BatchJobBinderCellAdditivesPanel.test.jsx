import { fireEvent, render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import BatchJobBinderCellAdditivesPanel from '../BatchJobBinderCellAdditivesPanel'

// Mirror the real chipButtonClass prop contract (selected -> class string).
const chipButtonClass = (selected) => (selected ? 'chip chip-selected' : 'chip')

const EMPTY_SUMMARY = {
  systemRows: [],
  rows: [],
  referenceSystemKey: null,
  totalAdditiveWeight: 0,
}

function renderPanel(overrides = {}) {
  const props = {
    additiveTypeOptions: ['SBS', 'PPA'],
    selectedAdditiveTypes: [],
    toggleAdditiveType: vi.fn(),
    chipButtonClass,
    additiveSummary: EMPTY_SUMMARY,
    additiveCatalog: {
      SBS: { mol_id: 'SBS', name: 'SBS', is_submittable: true },
      PPA: {
        mol_id: 'PPA',
        name: 'PPA',
        is_submittable: false,
        blocked_reason: 'Artifact not found',
      },
    },
    setAdditiveCounts: vi.fn(),
    additiveSummaryGrid: 'grid-cols-5',
    ...overrides,
  }
  const utils = render(<BatchJobBinderCellAdditivesPanel {...props} />)
  return { props, ...utils }
}

// Parity with single-job BinderAdditivesPanel: additives whose FF route is not
// submittable (is_submittable === false) are disabled, not silently selectable.
describe('BatchJobBinderCellAdditivesPanel — blocked additive parity with single job', () => {
  it('disables a non-submittable additive chip and surfaces its blocked_reason', () => {
    renderPanel()
    const blocked = screen.getByRole('button', { name: 'PPA' })
    expect(blocked).toBeDisabled()
    expect(blocked.getAttribute('title')).toContain('Artifact not found')
  })

  it('keeps submittable additive chips enabled and toggleable', () => {
    const { props } = renderPanel()
    const ok = screen.getByRole('button', { name: 'SBS' })
    expect(ok).not.toBeDisabled()
    fireEvent.click(ok)
    expect(props.toggleAdditiveType).toHaveBeenCalledWith('SBS')
  })

  it('does not toggle when a blocked chip is clicked', () => {
    const { props } = renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'PPA' }))
    expect(props.toggleAdditiveType).not.toHaveBeenCalledWith('PPA')
  })
})
