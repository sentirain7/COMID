import {
  ELEMENT_COLORS,
  normalizeElementSymbol,
  getElementColorHex,
  getElementColorCss,
} from '../../components/molecule-viewer/elementColors'
import { parseAtomLine } from '../../components/molecule-viewer/xyzParser'

describe('elementColors', () => {
  describe('normalizeElementSymbol', () => {
    it('returns uppercase for single-char lowercase', () => {
      expect(normalizeElementSymbol('c')).toBe('C')
      expect(normalizeElementSymbol('h')).toBe('H')
    })

    it('capitalizes first letter and lowercases rest', () => {
      expect(normalizeElementSymbol('SI')).toBe('Si')
      expect(normalizeElementSymbol('si')).toBe('Si')
      expect(normalizeElementSymbol('na')).toBe('Na')
    })

    it('strips leading/trailing whitespace', () => {
      expect(normalizeElementSymbol('  C  ')).toBe('C')
      expect(normalizeElementSymbol(' Fe ')).toBe('Fe')
    })

    it('returns X for empty or falsy input', () => {
      expect(normalizeElementSymbol('')).toBe('X')
      expect(normalizeElementSymbol(null)).toBe('X')
      expect(normalizeElementSymbol(undefined)).toBe('X')
    })

    it('handles element symbols with trailing numbers (e.g. from LAMMPS types)', () => {
      // normalizeElementSymbol treats numeric chars as lowercase,
      // so "C1" becomes "C1" (first char upper, rest lower)
      const result = normalizeElementSymbol('C1')
      expect(result[0]).toBe('C')
    })
  })

  describe('getElementColorHex', () => {
    it('returns a number for known elements', () => {
      const hex = getElementColorHex('C')
      expect(typeof hex).toBe('number')
      expect(hex).toBe(ELEMENT_COLORS.C)
    })

    it('returns fallback color for unknown elements', () => {
      expect(getElementColorHex('Xx')).toBe(ELEMENT_COLORS.X)
      expect(getElementColorHex('?')).toBe(ELEMENT_COLORS.X)
    })

    it('normalizes element before lookup', () => {
      expect(getElementColorHex('fe')).toBe(ELEMENT_COLORS.Fe)
      expect(getElementColorHex('SI')).toBe(ELEMENT_COLORS.Si)
    })
  })

  describe('getElementColorCss', () => {
    it('returns a CSS hex string starting with #', () => {
      const css = getElementColorCss('O')
      expect(css).toMatch(/^#[0-9a-f]{6}$/)
    })

    it('returns correct color for carbon', () => {
      // C is 0x606060 => '#606060'
      expect(getElementColorCss('C')).toBe('#606060')
    })

    it('returns correct color for hydrogen (white)', () => {
      // H is 0xffffff => '#ffffff'
      expect(getElementColorCss('H')).toBe('#ffffff')
    })

    it('returns fallback color for unknown element', () => {
      // X is 0xff00ff => '#ff00ff'
      expect(getElementColorCss('Zz')).toBe('#ff00ff')
    })
  })
})

describe('xyzParser', () => {
  describe('parseAtomLine', () => {
    it('parses a standard XYZ line', () => {
      const result = parseAtomLine('C  1.234  5.678  9.012')
      expect(result).toEqual({
        element: 'C',
        x: 1.234,
        y: 5.678,
        z: 9.012,
      })
    })

    it('parses a line with extra whitespace', () => {
      const result = parseAtomLine('  Si   12.3   -4.5   0.0  ')
      expect(result).toEqual({
        element: 'Si',
        x: 12.3,
        y: -4.5,
        z: 0.0,
      })
    })

    it('parses negative coordinates', () => {
      const result = parseAtomLine('Fe -1.0 -2.0 -3.0')
      expect(result).toEqual({
        element: 'Fe',
        x: -1.0,
        y: -2.0,
        z: -3.0,
      })
    })

    it('returns null for empty line', () => {
      expect(parseAtomLine('')).toBeNull()
    })

    it('returns null for line with fewer than 4 tokens', () => {
      expect(parseAtomLine('C 1.0 2.0')).toBeNull()
      expect(parseAtomLine('C')).toBeNull()
    })

    it('returns null for whitespace-only line', () => {
      expect(parseAtomLine('   ')).toBeNull()
    })

    it('handles tab-separated values', () => {
      const result = parseAtomLine('O\t1.0\t2.0\t3.0')
      expect(result).toEqual({
        element: 'O',
        x: 1.0,
        y: 2.0,
        z: 3.0,
      })
    })
  })
})
