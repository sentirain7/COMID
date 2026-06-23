/**
 * FF Parameters status section for MoleculePreviewPanel.
 * Shows artifact source_id, SSOT paths, consumers, and generation actions.
 *
 * v00.99.80: artifact status badge and generation_profile row removed — they
 * duplicated the FF badge in the top meta row of MoleculePreviewPanel
 * (which already encodes status + `(Robust)` suffix). This section is now
 * the single source of id/paths/actions; the top badge is the single
 * source of ready/pending/failed + profile.
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, Play, Stethoscope } from 'lucide-react'

export default function FFStatusSection({
  row,
  molId,
  onGenerate,
  onDiagnose,
  generatingId,
}) {
  const [showDetail, setShowDetail] = useState(false)

  if (!row) return null

  const busy = generatingId === row.source_id
  const isPassthrough = row.is_passthrough

  // v00.99.76: 2-column layout for text info so the section uses horizontal
  // space and leaves more vertical room below for Detail expansion without
  // requiring an internal scrollbar.
  return (
    <div className="border-t border-slate-700 pt-2 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide"
            title={`source_id: ${row.source_id}`}>
          FF Parameters
        </h4>
      </div>

      {/* Two-column text grid — fields are distributed so each column has
          roughly balanced content. Longer values use `truncate` with the
          full string available via `title` for tooltip. */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        {row.catalog && (
          <div className="text-slate-500 truncate" title={row.catalog}>
            <span className="text-slate-400">Catalog: </span>
            {row.catalog}
          </div>
        )}
        {(row.structure_file || row.primary_mol_id) && (
          <div className="text-slate-500 truncate" title={row.structure_file || `${row.primary_mol_id}.mol`}>
            <span className="text-slate-400">MOL: </span>
            {row.structure_file || `${row.primary_mol_id}.mol`}
          </div>
        )}
        <div className="text-slate-500 truncate" title={`organic_gaff2/${row.source_id}.json`}>
          <span className="text-slate-400">Artifact: </span>
          organic_gaff2/{row.source_id}.json
        </div>
        {row.generator && (
          <div className="text-slate-500 truncate" title={row.generator}>
            <span className="text-slate-400">Generator: </span>
            <span className={
              row.generator === 'curated_carbon_sp2' ? 'text-teal-400' :
              'text-slate-300'
            }>{row.generator}</span>
          </div>
        )}
        {row.failure_code && (
          <div className="text-red-400 font-mono truncate col-span-2" title={`${row.failure_code} @ ${row.stage}`}>
            {row.failure_code} @ {row.stage}
          </div>
        )}
        {row.recommended_action && (
          <div className="text-amber-400 truncate col-span-2" title={row.recommended_action}>
            {row.recommended_action}
          </div>
        )}
        {row.consumer_ids?.length > 1 && (
          <div className="text-slate-500 truncate col-span-2" title={row.consumer_ids.join(', ')}>
            <span className="text-slate-400">Consumers: </span>
            {row.consumer_ids.join(', ')}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-1.5">
        <button
          onClick={() => onGenerate?.(row.source_id)}
          disabled={busy || isPassthrough}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-slate-700 hover:bg-slate-600 text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Play size={10} />
          {busy ? 'Generating...' : 'Generate'}
        </button>

        <button
          onClick={() => onDiagnose?.(molId || row.primary_mol_id)}
          disabled={busy}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-slate-700 hover:bg-slate-600 text-slate-200 disabled:opacity-40"
        >
          <Stethoscope size={10} />
          Diagnose
        </button>

        {/* Detail toggle pushed to the right edge to save vertical space */}
        {(row.stderr_excerpt || row.preflight) && (
          <button
            onClick={() => setShowDetail((v) => !v)}
            className="ml-auto flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-300"
          >
            {showDetail ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            Detail
          </button>
        )}
      </div>

      {/* Expanded detail — no internal max-h so the content renders in full
          (up to the panel's fixed height budget). The outer preview panel
          is `overflow-hidden`, so if a pathological payload still exceeds
          the budget, the overflow is clipped rather than presented as a
          scroll handle. */}
      {showDetail && (row.stderr_excerpt || row.preflight) && (
        <pre className="text-[9px] text-slate-500 bg-slate-900 rounded p-2 whitespace-pre-wrap break-all">
          {row.stderr_excerpt || JSON.stringify(row.preflight, null, 2)}
        </pre>
      )}
    </div>
  )
}
