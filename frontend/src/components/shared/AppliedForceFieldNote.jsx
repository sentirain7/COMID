/**
 * Applied Force Field Note — read-only label of the FF stack applied to the composition.
 *
 * The FF is applied deterministically via each molecule's ff_assignment route (not a user
 * choice), so it shows "applied" rather than a "choice". When an inorganic (SiO2, etc.)
 * additive is included, it dynamically indicates that INTERFACE FF is automatically combined
 * on top of GAFF2. Shared by single-job and batch-job.
 */
import clsx from 'clsx'
import { formatAppliedForceFields, getAppliedForceFields } from '../../lib/forceFieldStack'

export function AppliedForceFieldNote({ ffType, additiveRoutes = [], className }) {
  const stack = getAppliedForceFields(ffType, additiveRoutes)
  const multi = stack.length > 1
  return (
    <p
      className={clsx('text-[10px] mt-1', multi ? 'text-cyan-400/90' : 'text-slate-500', className)}
      aria-label="Applied force fields"
    >
      Applied FF: {formatAppliedForceFields(ffType, additiveRoutes)}
    </p>
  )
}

export default AppliedForceFieldNote
