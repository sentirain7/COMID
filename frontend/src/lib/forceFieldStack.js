/**
 * ff_assignment route → applied FF label (SSOT mapping).
 *
 * Maps one-to-one to the backend typing_router routes (`organic_curated_artifact`/
 * `inorganic_profile`/`ionic_profile`/`blocked`). When a new FF route is added to the
 * backend, adding a single line to this table automatically reflects it in both the
 * single-job and batch-job labels (single SSOT). A route not present in this table is
 * exposed by its identifier as-is to surface a "missing label" — it is not silently
 * buried under GAFF2.
 */
export const ROUTE_FF_LABEL = {
  organic_curated_artifact: 'GAFF2',
  inorganic_profile: 'INTERFACE FF',
  ionic_profile: 'Ionic FF',
}

/**
 * Dynamically computes the force field stack actually applied to the composition
 * (for read-only labeling).
 *
 * The FF is not something the user "selects" per molecule; the backend deterministically
 * enforces it via each molecule's ff_assignment route (governance SSOT). The organic binder
 * is always GAFF2, and when an inorganic additive (SiO2, NanoClay, etc.) is included, the FF
 * corresponding to its route (e.g., INTERFACE FF) is automatically combined via
 * Lorentz-Berthelot mixing. The UI therefore labels this as "applied" rather than a "choice".
 *
 * @param {string} ffType - simulation track ('bulk_ff_gaff2' | 'reaxff')
 * @param {string[]} additiveRoutes - list of ff_assignment routes for the selected additives
 * @returns {string[]} array of applied FF names
 */
export function getAppliedForceFields(ffType, additiveRoutes = []) {
  // ReaxFF is a reactive track applied as a single FF to the entire system (no GAFF2/INTERFACE).
  if (ffType === 'reaxff') return ['ReaxFF']
  const stack = ['GAFF2'] // organic binder = organic_curated_artifact
  for (const route of additiveRoutes) {
    // organic/blocked routes are already covered by the binder's GAFF2 → no extra label.
    if (!route || route === 'organic_curated_artifact' || route === 'blocked') continue
    const label = ROUTE_FF_LABEL[route] || route // expose unknown routes as-is
    if (!stack.includes(label)) stack.push(label)
  }
  return stack
}

/**
 * Converts the applied FF stack into a human-readable label. When there are multiple FFs,
 * it states the mixing rule.
 *
 * @param {string} ffType - simulation track
 * @param {string[]} additiveRoutes - list of additive routes
 * @returns {string} e.g., "GAFF2" or "GAFF2 + INTERFACE FF (Lorentz-Berthelot mixing)"
 */
export function formatAppliedForceFields(ffType, additiveRoutes = []) {
  const stack = getAppliedForceFields(ffType, additiveRoutes)
  if (stack.length <= 1) return stack[0]
  return `${stack.join(' + ')} (Lorentz-Berthelot mixing)`
}
