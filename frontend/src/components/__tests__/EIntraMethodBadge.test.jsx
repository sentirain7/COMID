import { render, screen } from '@testing-library/react'
import { EIntraMethodBadge } from '../shared/EIntraMethodBadge'

describe('EIntraMethodBadge', () => {
  it('renders canonical adaptive label for CED scope', () => {
    render(
      <EIntraMethodBadge
        method="single_molecule_vacuum_adaptive_cutoff"
        source="metric:cohesive_energy_density"
        scope="ced"
      />,
    )

    expect(screen.getByText('CED basis')).toBeInTheDocument()
    expect(screen.getByText('Vacuum Adaptive')).toBeInTheDocument()
    expect(
      screen.getByTitle(/CED basis • Vacuum Adaptive • metric:cohesive_energy_density/i),
    ).toBeInTheDocument()
  })

  it('normalizes legacy alias for e_intra scope', () => {
    render(
      <EIntraMethodBadge
        method="single_molecule_vacuum_extended_cutoff"
        source="metadata:experiment"
        scope="e_intra"
      />,
    )

    expect(screen.getByText('E_intra basis')).toBeInTheDocument()
    expect(screen.getByText('Vacuum Adaptive')).toBeInTheDocument()
  })
})
