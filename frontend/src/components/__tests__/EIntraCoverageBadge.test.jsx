import { render, screen } from '@testing-library/react'
import { EIntraCoverageBadge } from '../shared/EIntraCoverageBadge'

describe('EIntraCoverageBadge', () => {
  it('renders N/A when coverage is null', () => {
    render(<EIntraCoverageBadge coverage={null} />)
    expect(screen.getByText('N/A')).toBeInTheDocument()
  })

  it('renders Done when coverage is complete', () => {
    render(
      <EIntraCoverageBadge
        coverage={{ computed_count: 12, required_count: 12, needs_calc: false }}
      />,
    )
    expect(screen.getByTitle('Done (12/12) [method: Vacuum 12 Å]')).toBeInTheDocument()
    expect(screen.getByText(/E_intra·Vacuum 12 Å/)).toBeInTheDocument()
    expect(screen.getByText(/12\/12/)).toBeInTheDocument()
  })

  it('renders Partial when some computed', () => {
    render(
      <EIntraCoverageBadge
        coverage={{ computed_count: 5, required_count: 12, needs_calc: true }}
      />,
    )
    expect(screen.getByTitle('Partial (5/12) [method: Vacuum 12 Å]')).toBeInTheDocument()
    expect(screen.getByText(/5\/12/)).toBeInTheDocument()
  })

  it('renders Need calc when nothing computed', () => {
    render(
      <EIntraCoverageBadge
        coverage={{ computed_count: 0, required_count: 12, needs_calc: true }}
      />,
    )
    expect(screen.getByTitle('Need calc [method: Vacuum 12 Å]')).toBeInTheDocument()
  })

  it('renders a human label for historical Method 2 rows', () => {
    render(
      <EIntraCoverageBadge
        coverage={{
          computed_count: 3,
          required_count: 12,
          needs_calc: true,
          method: 'single_molecule_periodic',
        }}
      />,
    )

    expect(screen.getByTitle('Partial (3/12) [method: Periodic PPPM]')).toBeInTheDocument()
    expect(screen.getByText(/E_intra·Periodic PPPM/)).toBeInTheDocument()
  })
})
