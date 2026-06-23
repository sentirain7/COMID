import {
  formatNumber,
  sanitizeNameToken,
  formatSizeAngstrom,
  formatArtifactLabel,
  stripComponentPrefix,
  saraTypeFromMolId,
  formatStepK,
  formatCompactDate,
  formatElapsedDuration,
} from '../formatters'

describe('formatters', () => {
  describe('formatNumber', () => {
    it('formats with default 1 decimal', () => {
      expect(formatNumber(3.14159)).toBe('3.1')
    })
    it('handles null', () => {
      expect(formatNumber(null)).toBe('0.0')
    })
  })

  describe('sanitizeNameToken', () => {
    it('strips whitespace and special chars', () => {
      expect(sanitizeNameToken('  Hello World! ')).toBe('HelloWorld')
    })
    it('returns default fallback for empty', () => {
      expect(sanitizeNameToken('')).toBe('na')
    })
    it('accepts custom fallback', () => {
      expect(sanitizeNameToken('', 'component')).toBe('component')
    })
    it('keeps dots, hyphens, underscores', () => {
      expect(sanitizeNameToken('file-name_v1.2')).toBe('file-name_v1.2')
    })
  })

  describe('formatSizeAngstrom', () => {
    it('formats finite number', () => {
      expect(formatSizeAngstrom(42.567)).toBe('42.6')
    })
    it('returns dash for non-finite', () => {
      expect(formatSizeAngstrom('abc')).toBe('-')
      expect(formatSizeAngstrom(undefined)).toBe('-')
    })
    it('formats zero', () => {
      expect(formatSizeAngstrom(0)).toBe('0.0')
      expect(formatSizeAngstrom(null)).toBe('0.0')
    })
  })

  describe('formatArtifactLabel', () => {
    it('extracts filename from path', () => {
      expect(formatArtifactLabel('/home/user/data.lammps')).toBe('data.lammps')
    })
    it('handles Windows paths', () => {
      expect(formatArtifactLabel('C:\\Users\\data.lammps')).toBe('data.lammps')
    })
    it('returns dash for falsy', () => {
      expect(formatArtifactLabel(null)).toBe('-')
      expect(formatArtifactLabel('')).toBe('-')
    })
  })

  describe('stripComponentPrefix', () => {
    it('strips AR- prefix', () => {
      expect(stripComponentPrefix('AR-PHPN')).toBe('PHPN')
    })
    it('strips RE- prefix', () => {
      expect(stripComponentPrefix('RE-Quin')).toBe('Quin')
    })
    it('strips SA- prefix', () => {
      expect(stripComponentPrefix('SA-Squalane')).toBe('Squalane')
    })
    it('leaves non-SARA prefixes intact', () => {
      expect(stripComponentPrefix('AS-Pyrrole')).toBe('AS-Pyrrole')
    })
  })

  describe('saraTypeFromMolId', () => {
    it('identifies aromatic', () => {
      expect(saraTypeFromMolId('AR-PHPN')).toBe('aromatic')
    })
    it('identifies resin', () => {
      expect(saraTypeFromMolId('RE-Quin')).toBe('resin')
    })
    it('identifies saturate', () => {
      expect(saraTypeFromMolId('SA-Squalane')).toBe('saturate')
    })
    it('defaults to aromatic', () => {
      expect(saraTypeFromMolId('unknown')).toBe('aromatic')
      expect(saraTypeFromMolId(null)).toBe('aromatic')
    })
  })

  describe('formatStepK', () => {
    it('formats thousands with k suffix', () => {
      expect(formatStepK(1500000)).toBe('1500k')
      expect(formatStepK(1000)).toBe('1k')
    })
    it('keeps small numbers as-is', () => {
      expect(formatStepK(999)).toBe('999')
    })
    it('returns dash for null', () => {
      expect(formatStepK(null)).toBe('-')
    })
  })

  describe('formatCompactDate', () => {
    it('returns dash for falsy', () => {
      expect(formatCompactDate(null)).toBe('-')
      expect(formatCompactDate('')).toBe('-')
    })
    it('returns dash for invalid date', () => {
      expect(formatCompactDate('not-a-date')).toBe('-')
    })
    it('formats valid ISO date', () => {
      const result = formatCompactDate('2026-03-17T05:30:00Z')
      expect(result).toMatch(/\d{6}\s\d{2}:\d{2}/)
    })
  })

  describe('formatElapsedDuration', () => {
    it('formats hours and minutes', () => {
      expect(formatElapsedDuration(7500)).toBe('2h 5m')
    })
    it('formats minutes only', () => {
      expect(formatElapsedDuration(300)).toBe('5m')
    })
    it('returns dash for non-finite', () => {
      expect(formatElapsedDuration(NaN)).toBe('-')
      expect(formatElapsedDuration(-1)).toBe('-')
    })
  })
})
