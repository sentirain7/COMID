export const formatNumber = (value, fractionDigits = 1) =>
  new Intl.NumberFormat('en-US', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(Number(value || 0))

/**
 * Sanitize a string for use as a name token (file names, exp_id segments).
 * Strips whitespace and non-alphanumeric chars (except . - _).
 */
export const sanitizeNameToken = (value, fallback = 'na') => {
  const normalized = String(value || '')
    .trim()
    .replace(/\s+/g, '')
    .replace(/[^A-Za-z0-9._-]/g, '')
  return normalized || fallback
}

/** Format a numeric value as Angstrom size (e.g. "42.3") */
export const formatSizeAngstrom = (value) => {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(1) : '-'
}

/** Extract filename from a path string */
export const formatArtifactLabel = (pathValue) => {
  if (!pathValue) return '-'
  const normalized = String(pathValue).replace(/\\/g, '/')
  const parts = normalized.split('/')
  return parts[parts.length - 1] || normalized
}

/** Strip SARA prefix from a mol_id (e.g. "AR-PHPN" → "PHPN") */
export const stripComponentPrefix = (molId) => String(molId || '').replace(/^(AR|RE|SA)-/, '')

/** Infer SARA type from mol_id prefix */
export const saraTypeFromMolId = (molId) => {
  const value = String(molId || '')
  if (value.startsWith('AR-')) return 'aromatic'
  if (value.startsWith('RE-')) return 'resin'
  if (value.startsWith('SA-')) return 'saturate'
  return 'aromatic'
}

/** Format step count with k suffix (e.g. 1500000 → "1500k") */
export const formatStepK = (v) => {
  if (v == null) return '-'
  return v >= 1000 ? `${Math.round(v / 1000)}k` : String(v)
}

/** Format ISO date to compact Korean format (e.g. "260317 14:30") */
export const formatCompactDate = (value) => {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  const parts = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(d)
  const token = (type) => parts.find((p) => p.type === type)?.value ?? '00'
  const yy = token('year')
  const mm = token('month')
  const dd = token('day')
  const hh = token('hour')
  const mi = token('minute')
  return `${yy}${mm}${dd} ${hh}:${mi}`
}

/** Format elapsed seconds to human-readable duration (e.g. "2h 15m") */
export const formatElapsedDuration = (value) => {
  const seconds = Number(value)
  if (!Number.isFinite(seconds) || seconds < 0) return '-'
  const totalMinutes = Math.floor(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}
