import clsx from 'clsx'
import { CATEGORY_TEXT_COLORS } from '../../lib/constants'
import { getDisplayMolTitle } from './helpers'
import { EIntraMatrix } from './EIntraMatrix'

function capitalize(str) {
  if (!str) return ''
  return str.charAt(0).toUpperCase() + str.slice(1).replace(/_/g, ' ')
}

// Uniform badge size — matches CategoryBadge for consistent table column widths.
const TABLE_BADGE_BASE = 'inline-flex items-center justify-center w-20 px-1.5 py-0.5 rounded text-[10px] border overflow-hidden'
// Wider variant for FF Type — accommodates profile suffix like "GAFF2-robust".
const TYPE_BADGE_BASE = 'inline-flex items-center justify-center w-24 px-1.5 py-0.5 rounded text-[10px] border overflow-hidden'

function Badge({ label, colorClass, title, widthClass }) {
  const base = widthClass || TABLE_BADGE_BASE
  return (
    <span className={clsx(base, colorClass)} title={title || label}>
      <span className="truncate">{label}</span>
    </span>
  )
}

// FF Type — FF family + generation profile variant.
// For organic GAFF2, the profile (baseline / sqm_robust) reflects both bonded
// (atom typing) and nonbonded (AM1-BCC charges) parameterization together,
// so it is conveyed as a single suffix rather than split columns.
export function FFTypeBadge({ mol, adminRow }) {
  const route = mol.route
  if (route === 'water_model')
    return <Badge label="TIP3P" colorClass="bg-blue-500/15 text-blue-300 border-blue-500/30" title="TIP3P water model (built-in, rigid)" widthClass={TYPE_BADGE_BASE} />
  if (route === 'inorganic_profile')
    return <Badge label="INTERFACE" colorClass="bg-cyan-500/15 text-cyan-300 border-cyan-500/30" title="INTERFACE FF (mineral LJ — crystal frozen, no bonded terms)" widthClass={TYPE_BADGE_BASE} />
  if (route === 'ionic_profile')
    return <Badge label="Ionic" colorClass="bg-violet-500/15 text-violet-300 border-violet-500/30" title="Ionic profile (curating)" widthClass={TYPE_BADGE_BASE} />
  // organic_curated_artifact — check generator first, then profile
  const generator = adminRow?.generator
  if (generator === 'curated_carbon_sp2')
    return <Badge label="Curated" colorClass="bg-teal-500/15 text-teal-300 border-teal-500/30" title="Curated carbon sp2 artifact (hand-verified GAFF2 ca/ha)" widthClass={TYPE_BADGE_BASE} />
  const profile = adminRow?.generation_profile
  if (profile === 'sqm_robust')
    return <Badge label="GAFF2-robust" colorClass="bg-orange-500/15 text-orange-300 border-orange-500/30" title="GAFF2 with sqm_robust antechamber profile (bonded + nonbonded re-parameterized)" widthClass={TYPE_BADGE_BASE} />
  if (profile === 'baseline')
    return <Badge label="GAFF2-base" colorClass="bg-indigo-500/15 text-indigo-300 border-indigo-500/30" title="GAFF2 baseline profile (default antechamber + AM1-BCC)" widthClass={TYPE_BADGE_BASE} />
  // Artifact exists but no admin sidecar → show "GAFF2" without profile suffix
  if (mol.is_artifact_complete) {
    return <Badge label="GAFF2" colorClass="bg-indigo-500/10 text-indigo-300/70 border-indigo-500/20" title="GAFF2 artifact exists (generation profile unknown)" widthClass={TYPE_BADGE_BASE} />
  }
  // No adminRow, no artifact → truly pending
  return <Badge label="—" colorClass="bg-slate-700/20 text-slate-500 border-slate-700" title="Pending (no artifact generated yet)" widthClass={TYPE_BADGE_BASE} />
}

// FF Status — pure generation state. Profile info (robust vs base) is carried
// by FFTypeBadge; this column shows only Ready / Failed / Pending / —.
function FFStatusBadge({ mol, adminRow }) {
  const route = mol.route
  // Built-in route families — FF is hand-curated / parameterless → always ready
  if (route === 'water_model' || route === 'inorganic_profile' || route === 'ionic_profile') {
    return <Badge label="Ready" colorClass="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" title="Built-in FF (always ready)" />
  }
  // organic_curated_artifact (or legacy/unset) — drive from adminRow
  if (adminRow) {
    const s = adminRow.artifact_status
    if (s === 'complete')
      return <Badge label="Ready" colorClass="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" title="Artifact complete" />
    if (s === 'generating')
      return <Badge label="Generating" colorClass="bg-cyan-500/15 text-cyan-300 border-cyan-500/30" title="FF generation in progress" />
    if (s === 'failed')
      return <Badge label="Failed" colorClass="bg-red-500/15 text-red-300 border-red-500/30" title={`Failed: ${adminRow.failure_code || 'unknown'}`} />
    return <Badge label="Pending" colorClass="bg-slate-700/30 text-slate-400 border-slate-600" title={`Status: ${s || 'pending'}`} />
  }
  if (mol.is_artifact_complete)
    return <Badge label="Ready" colorClass="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" title="Artifact on disk" />
  return <Badge label="Pending" colorClass="bg-slate-700/30 text-slate-400 border-slate-600" title="No admin record" />
}

/**
 * Table listing molecules with selection and FF generation support.
 *
 * Props:
 *   molecules        - array of molecule objects to display
 *   selectedMolId    - mol_id of the currently selected row
 *   onSelectMolId    - callback(mol_id) when a row is clicked
 *   adminRowMap      - Map<mol_id, adminRow> for FF status lookup
 *   checkedMolIds    - Set<mol_id> of checked molecules for batch FF generation
 *   onToggleChecked  - callback(mol_id) to toggle checkbox
 */
export function MoleculeTable({
  molecules,
  selectedMolId,
  onSelectMolId,
  adminRowMap,
  checkedMolIds,
  onToggleChecked,
}) {
  const allChecked = molecules.length > 0 && checkedMolIds?.size === molecules.length
  const someChecked = checkedMolIds?.size > 0 && !allChecked

  return (
    <div className="card overflow-hidden h-full flex flex-col">
      {/* v00.99.79: fill the parent grid cell and scroll vertically inside
          the table. This keeps table height identical across tabs — the
          tallest tab (Asphalt Binder / Long Term Aging) no longer makes
          the scroll container grow to a different size than the other
          tabs. Sticky header keeps the column labels visible while the
          operator scrolls rows. */}
      <div className="overflow-auto flex-1 min-h-0">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-800/80 border-b border-slate-700 sticky top-0 z-10">
            <tr className="text-center text-slate-300">
              <th className="px-2 py-2 font-medium w-8">
                <input
                  type="checkbox"
                  checked={allChecked}
                  ref={(el) => { if (el) el.indeterminate = someChecked }}
                  onChange={() => {
                    if (allChecked) {
                      molecules.forEach((m) => onToggleChecked?.(m.mol_id, false))
                    } else {
                      molecules.forEach((m) => onToggleChecked?.(m.mol_id, true))
                    }
                  }}
                  className="rounded border-slate-600 bg-slate-700 text-cyan-500 focus:ring-cyan-500/30"
                />
              </th>
              <th className="px-2 py-2 font-medium w-8">#</th>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Atoms</th>
              <th className="px-3 py-2 font-medium">MW</th>
              <th className="px-3 py-2 font-medium">Category</th>
              <th className="px-3 py-2 font-medium">FF Type</th>
              <th className="px-3 py-2 font-medium">FF Status</th>
              <th className="px-2 py-2 font-medium" title="E_intra coverage (213–433 K)">E_intra</th>
            </tr>
          </thead>
          <tbody>
            {molecules.map((mol, index) => {
              const selected = mol.mol_id === selectedMolId
              const checked = checkedMolIds?.has(mol.mol_id) || false
              const adminRow = adminRowMap?.get(mol.mol_id) || null
              return (
                <tr
                  key={mol.mol_id}
                  onClick={() => onSelectMolId(mol.mol_id)}
                  className={clsx(
                    'border-b border-slate-800/80 cursor-pointer text-center',
                    selected ? 'bg-cyan-500/10' : 'hover:bg-slate-800/50'
                  )}
                >
                  <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleChecked?.(mol.mol_id)}
                      className="rounded border-slate-600 bg-slate-700 text-cyan-500 focus:ring-cyan-500/30"
                    />
                  </td>
                  <td className="px-2 py-2 text-[10px] text-slate-500 font-mono">
                    {index + 1}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap" title={mol.mol_id}>
                    <div className="text-slate-100">{getDisplayMolTitle(mol)}</div>
                  </td>
                  <td className="px-3 py-2 text-slate-200">{mol.atom_count || '-'}</td>
                  <td className="px-3 py-2 text-slate-200">{mol.molecular_weight?.toFixed(2) || '-'}</td>
                  <td className="px-3 py-2">
                    {mol.display_category ? (
                      <span
                        className={clsx(
                          'text-xs font-bold',
                          CATEGORY_TEXT_COLORS[mol.display_category] || 'text-slate-400'
                        )}
                        title={mol.display_category}
                      >
                        {capitalize(mol.display_category)}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex justify-center">
                      <FFTypeBadge mol={mol} adminRow={adminRow} />
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex justify-center">
                      <FFStatusBadge mol={mol} adminRow={adminRow} />
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex justify-center">
                      <EIntraMatrix coverage={mol.e_intra_coverage} />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
