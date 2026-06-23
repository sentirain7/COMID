export const DEFAULT_E_INTRA_METHOD = 'single_molecule_vacuum'
export const DEFAULT_E_INTRA_METHOD_STORAGE_KEY = 'settings.default_e_intra_method'

export const E_INTRA_METHOD_OPTIONS = [
  {
    value: 'single_molecule_vacuum',
    label: 'Vacuum 12 Å',
    shortLabel: 'Vacuum 12 Å',
  },
  {
    value: 'single_molecule_vacuum_adaptive_cutoff',
    label: 'Vacuum Adaptive',
    shortLabel: 'Vacuum Adaptive',
  },
  {
    value: 'single_molecule_periodic',
    label: 'Periodic PPPM',
    shortLabel: 'Periodic PPPM',
  },
]

const E_INTRA_METHOD_LEGACY_ALIASES = {
  single_molecule_vacuum_extended_cutoff: 'single_molecule_vacuum_adaptive_cutoff',
}

// Public submit/settings surfaces must use this filtered list. Method 2 remains
// reserved for deferred/internal workflows and may still appear in read-only
// labels for historical or experimental rows.
export const SUBMISSION_E_INTRA_METHOD_OPTIONS = E_INTRA_METHOD_OPTIONS.filter(
  (option) => option.value !== 'single_molecule_periodic',
)

const SUBMISSION_E_INTRA_METHOD_LABELS = Object.fromEntries(
  SUBMISSION_E_INTRA_METHOD_OPTIONS.map((option) => [option.value, option.label]),
)

const SUBMISSION_E_INTRA_METHOD_SHORT_LABELS = Object.fromEntries(
  SUBMISSION_E_INTRA_METHOD_OPTIONS.map((option) => [option.value, option.shortLabel]),
)

const E_INTRA_METHOD_LABELS = Object.fromEntries(
  E_INTRA_METHOD_OPTIONS.map((option) => [option.value, option.label]),
)

const E_INTRA_METHOD_SHORT_LABELS = Object.fromEntries(
  E_INTRA_METHOD_OPTIONS.map((option) => [option.value, option.shortLabel]),
)

const E_INTRA_METHOD_PROFILES = {
  single_molecule_vacuum: {
    studyLabel: 'Vacuum 12 Å',
    boundary: 's s s',
    kspace: 'none',
    pairStyle: 'lj/cut/coul/cut',
  },
  single_molecule_vacuum_adaptive_cutoff: {
    studyLabel: 'Vacuum Adaptive',
    boundary: 's s s',
    kspace: 'none',
    pairStyle: 'lj/cut/coul/cut',
  },
  single_molecule_periodic: {
    studyLabel: 'Periodic PPPM',
    boundary: 'p p p',
    kspace: 'PPPM',
    pairStyle: 'lj/cut/coul/long',
  },
}

export function normalizeEIntraMethod(value) {
  const canonical = E_INTRA_METHOD_LEGACY_ALIASES[value] || value
  return E_INTRA_METHOD_LABELS[canonical] ? canonical : null
}

export function normalizeSubmissionEIntraMethod(value) {
  const canonical = E_INTRA_METHOD_LEGACY_ALIASES[value] || value
  return SUBMISSION_E_INTRA_METHOD_LABELS[canonical] ? canonical : null
}

export function getDefaultEIntraMethod(value) {
  return normalizeEIntraMethod(value) || DEFAULT_E_INTRA_METHOD
}

export function getDefaultSubmissionEIntraMethod(value) {
  return normalizeSubmissionEIntraMethod(value) || DEFAULT_E_INTRA_METHOD
}

export function getEIntraMethodLabel(value) {
  const method = getDefaultEIntraMethod(value)
  return E_INTRA_METHOD_LABELS[method]
}

export function getEIntraMethodShortLabel(value) {
  const method = getDefaultEIntraMethod(value)
  return E_INTRA_METHOD_SHORT_LABELS[method]
}

export function getSubmissionEIntraMethodLabel(value) {
  const method = getDefaultSubmissionEIntraMethod(value)
  return SUBMISSION_E_INTRA_METHOD_LABELS[method]
}

export function getSubmissionEIntraMethodShortLabel(value) {
  const method = getDefaultSubmissionEIntraMethod(value)
  return SUBMISSION_E_INTRA_METHOD_SHORT_LABELS[method]
}

export function getVisibleEIntraMethodDisplay(value) {
  const method = normalizeEIntraMethod(value)
  if (method) {
    return {
      supported: true,
      label: getEIntraMethodLabel(method),
      shortLabel: getEIntraMethodShortLabel(method),
    }
  }
  if (value) {
    return {
      supported: false,
      label: 'Deferred/internal method',
      shortLabel: null,
    }
  }
  return {
    supported: true,
    label: getSubmissionEIntraMethodLabel(DEFAULT_E_INTRA_METHOD),
    shortLabel: getSubmissionEIntraMethodShortLabel(DEFAULT_E_INTRA_METHOD),
  }
}

export function getEIntraMethodProfile(value) {
  const method = getDefaultEIntraMethod(value)
  return E_INTRA_METHOD_PROFILES[method]
}

export function getSubmissionEIntraMethodProfile(value) {
  const method = getDefaultSubmissionEIntraMethod(value)
  return E_INTRA_METHOD_PROFILES[method]
}

export function readStoredDefaultEIntraMethod() {
  if (typeof window === 'undefined') return null
  try {
    return normalizeSubmissionEIntraMethod(
      window.localStorage.getItem(DEFAULT_E_INTRA_METHOD_STORAGE_KEY),
    )
  } catch {
    return null
  }
}

export function persistDefaultEIntraMethod(value) {
  if (typeof window === 'undefined') return
  const method = getDefaultSubmissionEIntraMethod(value)
  try {
    window.localStorage.setItem(DEFAULT_E_INTRA_METHOD_STORAGE_KEY, method)
  } catch {
    // Ignore storage failures; submit UIs still fall back to Method 1.
  }
}

export function withDefaultEIntraMethod(settings, { useLocalFallback = false } = {}) {
  const baseSettings = settings && typeof settings === 'object' ? settings : {}
  const serverMethod = normalizeEIntraMethod(baseSettings.default_e_intra_method)
  const method = serverMethod
    || (useLocalFallback ? readStoredDefaultEIntraMethod() : null)
    || DEFAULT_E_INTRA_METHOD
  return {
    ...baseSettings,
    default_e_intra_method: method,
  }
}

export function withSubmissionDefaultEIntraMethod(
  settings,
  { useLocalFallback = false } = {},
) {
  const baseSettings = settings && typeof settings === 'object' ? settings : {}
  const serverMethod = normalizeSubmissionEIntraMethod(
    baseSettings.default_e_intra_method,
  )
  const method = serverMethod
    || (useLocalFallback ? readStoredDefaultEIntraMethod() : null)
    || DEFAULT_E_INTRA_METHOD
  return {
    ...baseSettings,
    default_e_intra_method: method,
  }
}
