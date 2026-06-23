// Atom color scheme (Material Studio/CPK-like)
export const ELEMENT_COLORS = {
  C: 0x606060,  // dark gray
  H: 0xffffff,  // white
  N: 0x3b5bdb,  // blue
  O: 0xe03131,  // red
  S: 0xf2c94c,  // yellow
  F: 0x90e050,  // green-yellow
  Si: 0xe6c78f, // tan
  P: 0xff8000,  // phosphorus
  Na: 0x8e7dff, // sodium
  K: 0x6f42c1,  // potassium
  Mg: 0x42b883, // magnesium
  Ca: 0x4caf50, // calcium
  Al: 0xb0b0b0, // aluminum
  Ti: 0x9aa0a6, // titanium
  Fe: 0xc46a2b, // iron
  Ni: 0x2fa866, // nickel
  Cu: 0xd08a2e, // copper
  Zn: 0x7f8db0, // zinc
  Cl: 0x1ff01f, // green
  Br: 0xa62929, // dark red
  I: 0x6a1b9a,  // iodine
  X: 0xff00ff,  // magenta (unknown)
}

export function normalizeElementSymbol(value) {
  const raw = String(value || '').trim()
  if (!raw) return 'X'
  if (raw.length === 1) return raw.toUpperCase()
  return raw[0].toUpperCase() + raw.slice(1).toLowerCase()
}

export function getElementColorHex(element) {
  const symbol = normalizeElementSymbol(element)
  return ELEMENT_COLORS[symbol] || ELEMENT_COLORS.X
}

export function getElementColorCss(element) {
  const hex = getElementColorHex(element)
  return `#${hex.toString(16).padStart(6, '0')}`
}
