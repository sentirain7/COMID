import { chipButtonClass } from '../chipButton'

describe('chipButtonClass', () => {
  it('returns active blue with font-medium by default', () => {
    const cls = chipButtonClass(true)
    expect(cls).toContain('bg-blue-500/20')
    expect(cls).toContain('border-blue-500/60')
    expect(cls).toContain('text-blue-300')
    expect(cls).toContain('font-medium')
  })

  it('returns inactive blue by default', () => {
    const cls = chipButtonClass(false)
    expect(cls).toContain('bg-slate-700/40')
    expect(cls).toContain('hover:bg-slate-700')
    expect(cls).toContain('font-medium')
  })

  it('supports cyan color scheme', () => {
    const cls = chipButtonClass(true, { colorScheme: 'cyan' })
    expect(cls).toContain('bg-cyan-500/20')
    expect(cls).toContain('text-cyan-300')
  })

  it('supports amber color scheme', () => {
    const cls = chipButtonClass(true, { colorScheme: 'amber' })
    expect(cls).toContain('bg-amber-500/20')
    expect(cls).toContain('text-amber-300')
  })

  it('omits font-medium when fontWeight is normal', () => {
    const cls = chipButtonClass(true, { fontWeight: 'normal' })
    expect(cls).not.toContain('font-medium')
    expect(cls).toContain('bg-blue-500/20')
  })

  it('combines amber + normal for BatchJobBinderCell pattern', () => {
    const cls = chipButtonClass(true, { colorScheme: 'amber', fontWeight: 'normal' })
    expect(cls).toContain('bg-amber-500/20')
    expect(cls).not.toContain('font-medium')
  })

  it('always includes base classes', () => {
    const cls = chipButtonClass(false, { colorScheme: 'cyan', fontWeight: 'normal' })
    expect(cls).toContain('px-2')
    expect(cls).toContain('py-1.5')
    expect(cls).toContain('rounded')
    expect(cls).toContain('text-xs')
    expect(cls).toContain('border')
    expect(cls).toContain('transition-colors')
  })
})
