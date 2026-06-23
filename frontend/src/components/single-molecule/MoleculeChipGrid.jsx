import { useMemo } from 'react'
import clsx from 'clsx'
import { SOURCE_TABS, AGING_TABS, getDisplayTitle } from './shared'
import { useEIntraLive } from '../../hooks/useEIntraLive'

// Wave 1: route/status badge taxonomy. The backend resolves the ff_assignment
// SSOT in resolve_ff_hint and surfaces (route, status) on every molecule
// list entry. This taxonomy is the single place that decides how each route
// shows up to the user.
// FF route labels for status display
const FF_ROUTE_LABELS = {
  organic_curated_artifact: 'FF-curated',
  inorganic_profile: 'FF-interface',
  water_model: 'FF-water',
  ionic_profile: 'FF-ionic',
  blocked: 'FF-blocked',
  organic_rdkit_legacy: 'FF-legacy',
}

const DOT_CLS = {
  emerald: 'bg-emerald-400',
  amber: 'bg-amber-400',
  red: 'bg-red-400',
  slate: 'bg-slate-500',
}

function StatusRow({ label, color, text }) {
  return (
    <div className="flex items-center justify-between gap-1">
      <span className="text-slate-500 truncate">{label}</span>
      <div className="flex items-center gap-0.5 shrink-0">
        {text && <span className="text-slate-400">{text}</span>}
        <span className={clsx('w-1.5 h-1.5 rounded-full', DOT_CLS[color])} />
      </div>
    </div>
  )
}

function StatusRows({ mol }) {
  // FF routing
  const route = mol.route
  const ffLabel = FF_ROUTE_LABELS[route] || 'FF'
  const ffColor = !route || route === 'blocked' ? 'red'
    : mol.status === 'blocked_placeholder' ? 'amber' : 'emerald'

  // E_intra coverage
  const cov = mol.e_intra_coverage
  const eCount = cov?.computed_count || 0
  const eTotal = cov?.required_count || 12
  const eColor = eCount >= eTotal ? 'emerald' : eCount > 0 ? 'amber' : 'red'
  const eText = eCount >= eTotal ? '' : `${eCount}/${eTotal}`

  return (
    <div className="flex flex-col gap-px mt-0.5 text-[7px] leading-tight">
      <StatusRow label={ffLabel} color={ffColor} />
      <StatusRow label="E_intra" color={eColor} text={eText} />
    </div>
  )
}

/**
 * MoleculeChipGrid — molecule selection as chip buttons.
 *
 * Single-select mode (default):
 *   selectedMolId: string|null, onSelect: (molId) => void
 *
 * Multi-select mode (multi=true):
 *   selectedMolIds: string[], onToggle: (molId) => void
 */
function MoleculeChipGrid({
  filteredMolecules,
  // Single-select props
  selectedMolId,
  onSelect,
  // Multi-select props
  multi = false,
  selectedMolIds = [],
  onToggle,
  // Shared props
  activeSourceTab,
  onSourceTabChange,
  activeAgingTab,
  onAgingTabChange,
  tabCounts,
  asphaltAgingCounts,
  chipButtonClass,
}) {
  // Subscribe to real-time E_intra updates.
  // PR 2 (Codex Round 9): scope the subscription to currently visible
  // molecules so a Method 1a write to molecule X does not stream every
  // unrelated event through this grid.  Falls back to "subscribe to all"
  // only when the visible list is empty (initial mount).
  const visibleMolIds = useMemo(
    () => (filteredMolecules || []).map((m) => m.mol_id),
    [filteredMolecules],
  )
  useEIntraLive(visibleMolIds.length > 0 ? visibleMolIds : null)

  const isSelected = (molId) => {
    if (multi) return selectedMolIds.includes(molId)
    return molId === selectedMolId
  }

  const handleClick = (molId) => {
    if (multi && onToggle) onToggle(molId)
    else if (onSelect) onSelect(molId)
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-2 flex-1 flex flex-col min-h-0">
      {/* Source tabs */}
      <div className="flex flex-wrap gap-1 mb-1.5">
        {SOURCE_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => onSourceTabChange(tab.key)}
            className={chipButtonClass(activeSourceTab === tab.key)}
          >
            {tab.label} ({tabCounts[tab.key] || 0})
          </button>
        ))}
        {multi && selectedMolIds.length > 0 && (
          <span className="text-[10px] text-slate-500 self-center ml-auto">{selectedMolIds.length} selected</span>
        )}
      </div>

      {/* Aging tabs (asphalt binder only) */}
      {activeSourceTab === 'asphalt_binder' && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {AGING_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => onAgingTabChange(tab.key)}
              className={chipButtonClass(activeAgingTab === tab.key, 'cyan')}
            >
              {tab.label} ({asphaltAgingCounts[tab.key] || 0})
            </button>
          ))}
        </div>
      )}

      {/* Molecule chip grid */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {filteredMolecules.length === 0 ? (
          <div className="text-xs text-slate-500 text-center py-3">No molecules</div>
        ) : (
          <div className="grid grid-cols-6 gap-1.5">
            {filteredMolecules.map((mol) => {
              const selected = isSelected(mol.mol_id)
              const blocked = mol.is_submittable === false
              const metaLine = `At: ${mol.atom_count || '?'}  MW: ${mol.molecular_weight ? mol.molecular_weight.toFixed(0) : '?'}`
              let chipTitle
              if (blocked) {
                chipTitle = `${mol.mol_id}\n⚠ ${mol.blocked_reason || 'blocked'}`
              } else {
                chipTitle = `${mol.mol_id}\n${metaLine}`
              }
              return (
                <button
                  key={mol.mol_id}
                  type="button"
                  onClick={() => !blocked && handleClick(mol.mol_id)}
                  disabled={blocked}
                  className={clsx(
                    chipButtonClass(selected),
                    '!px-1 !py-1 text-center',
                    blocked && '!opacity-40 !cursor-not-allowed',
                  )}
                  aria-pressed={selected}
                  title={chipTitle}
                >
                  <div className="text-[11px] font-medium truncate">{getDisplayTitle(mol)}</div>
                  <StatusRows mol={mol} />
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default MoleculeChipGrid
