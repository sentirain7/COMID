import { normalizeElementSymbol } from './elementColors'

export function extractElementsFromXyz(xyzData) {
  if (!xyzData) return []
  const lines = String(xyzData).split('\n')
  const nAtoms = Number.parseInt(lines[0], 10)
  if (!Number.isFinite(nAtoms) || nAtoms <= 0) return []
  const seen = new Set()
  for (let i = 2; i < 2 + nAtoms && i < lines.length; i += 1) {
    const symbol = normalizeElementSymbol(lines[i].trim().split(/\s+/)[0])
    if (symbol) seen.add(symbol)
  }
  return Array.from(seen)
}

export function parseAtomLine(line) {
  const tokens = []
  const n = line.length
  let i = 0

  while (i < n && tokens.length < 4) {
    while (i < n && line.charCodeAt(i) <= 32) i += 1
    if (i >= n) break
    const start = i
    while (i < n && line.charCodeAt(i) > 32) i += 1
    tokens.push(line.slice(start, i))
  }

  if (tokens.length < 4) return null
  return {
    element: tokens[0],
    x: Number.parseFloat(tokens[1]),
    y: Number.parseFloat(tokens[2]),
    z: Number.parseFloat(tokens[3]),
  }
}
