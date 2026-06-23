import { useState, useEffect } from 'react'

/**
 * Hook that forces a re-render whenever the color theme changes.
 *
 * colorPresets.js mutates module-level objects in-place (ANALYSIS_BG, SARA_COLORS, etc.)
 * but React doesn't detect object mutation. This hook listens for the
 * 'asphalt:theme-change' custom event dispatched by setColorPreset() / setAnalysisBg()
 * and bumps a version counter to trigger re-renders.
 *
 * @param {'chart' | 'analysis' | 'all'} scope - Which theme scope to listen for
 * @returns {number} version counter (unused by caller, just triggers re-render)
 */
export default function useThemeVersion(scope = 'all') {
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const handler = (e) => {
      if (scope === 'all' || e.detail?.scope === scope) {
        setVersion((v) => v + 1)
      }
    }
    window.addEventListener('asphalt:theme-change', handler)
    return () => window.removeEventListener('asphalt:theme-change', handler)
  }, [scope])

  return version
}
