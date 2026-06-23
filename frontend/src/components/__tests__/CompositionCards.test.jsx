import { fireEvent, render, screen } from '@testing-library/react'
import CompositionCards from '../CompositionCards'

describe('CompositionCards', () => {
  it('renders binder cards with compact molecule-chip styling', () => {
    render(
      <CompositionCards
        cards={[
          {
            key: 'mol:SA-Squalane',
            molId: 'SA-Squalane',
            title: 'SA-Squalane',
            saraType: 'saturate',
            count: 10,
            atomCount: 62,
            kind: 'binder',
          },
        ]}
      />,
    )

    const title = screen.getByText('SA-Squalane')
    const card = title.closest('div.rounded')
    expect(card).toHaveClass('border-slate-600')
    expect(card).toHaveClass('bg-slate-700/40')
    expect(title).toHaveClass('text-green-300')
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.queryByText('~620')).not.toBeInTheDocument()
  })

  it('keeps preview and editable count interactions working', () => {
    const onPreview = vi.fn()
    const onCountChange = vi.fn()

    render(
      <CompositionCards
        editable
        onPreview={onPreview}
        onCountChange={onCountChange}
        cards={[
          {
            key: 'mol:SA-Squalane',
            molId: 'SA-Squalane',
            title: 'SA-Squalane',
            count: 10,
            atomCount: 62,
            kind: 'binder',
            index: 0,
          },
        ]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /View SA-Squalane structure/i }))
    expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({ molId: 'SA-Squalane' }))

    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '12' } })
    expect(onCountChange).toHaveBeenCalledWith(0, 12)
  })
})
