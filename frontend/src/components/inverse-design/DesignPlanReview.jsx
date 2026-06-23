import { PIPELINE_MODE_BADGES } from '../../lib/constants'

function ModeBadge({ mode }) {
  const badge = PIPELINE_MODE_BADGES[mode] || {
    label: mode,
    className: 'bg-slate-600 text-slate-200',
  }
  return <span className={`px-2 py-0.5 rounded text-xs ${badge.className}`}>{badge.label}</span>
}

function CandidateSummary({ candidate, index }) {
  const comp = candidate.composition || {}
  const sara = ['asphaltene', 'resin', 'aromatic', 'saturate']
  return (
    <div className="bg-slate-700/30 rounded p-2 text-xs space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-slate-200">#{index + 1}</span>
        <span className="text-slate-400">{candidate.source}</span>
      </div>
      {candidate.binder_type && (
        <div className="text-slate-200">binder: {candidate.binder_type}</div>
      )}
      <div className="text-slate-300">
        {sara.map((k) => `${k.slice(0, 3)} ${Number(comp[k] ?? 0).toFixed(1)}`).join(' / ')}
        {comp.additive != null && ` / add ${Number(comp.additive).toFixed(1)}`}
      </div>
      {candidate.additive_type && (
        <div className="text-slate-400">additive: {candidate.additive_type}</div>
      )}
      {candidate.predicted_properties && (
        <div className="text-slate-400">
          {Object.entries(candidate.predicted_properties)
            .map(([k, v]) => `${k}: ${Number(v).toPrecision(3)}`)
            .join(', ')}
        </div>
      )}
    </div>
  )
}

/**
 * Wizard ② — plan review/approval (plan §8).
 *
 * Displays the preview_plan response (mode/rationale/candidates/DOE experiment
 * table/feasibility) and, on approval, returns plan/plan_hash as-is (§4.6 stateless).
 */
function DesignPlanReview({ plan, planHash, onApprove, onBack, approving, error }) {
  if (!plan) return null
  const rationale = plan.mode_rationale || {}
  const feasibility = plan.design?.feasibility

  return (
    <div className="space-y-4">
      <section className="flex items-center gap-3">
        <h3 className="text-slate-200 font-semibold">Plan review</h3>
        <ModeBadge mode={plan.mode} />
        <span className="text-slate-500 text-xs">hash {planHash}</span>
      </section>

      {plan.mode === 'bootstrap' && (
        <p className="text-amber-300/90 text-sm">
          Cold start: champion model unsupported or insufficient labels
          {rationale.label_starved_targets?.length
            ? ` (insufficient: ${rationale.label_starved_targets.join(', ')})`
            : ''}
          — space-filling DOE seed batch collects labels first.
        </p>
      )}

      {feasibility && (
        <p className="text-slate-400 text-sm">
          Feasibility: <span className="text-slate-200">{feasibility.status}</span>
          {feasibility.message ? ` — ${feasibility.message}` : ''}
        </p>
      )}

      <section>
        <h4 className="text-slate-300 text-sm font-semibold mb-1">
          Targets ({(plan.targets || []).length})
        </h4>
        <div className="flex flex-wrap gap-2 text-xs">
          {(plan.targets || []).map((t) => (
            <span key={t.metric_name} className="bg-slate-700/50 rounded px-2 py-1 text-slate-200">
              {t.metric_name} {t.target_min != null && `≥ ${t.target_min}`}
              {t.target_min != null && t.target_max != null && ' · '}
              {t.target_max != null && `≤ ${t.target_max}`} {t.unit}
            </span>
          ))}
        </div>
      </section>

      <section>
        <h4 className="text-slate-300 text-sm font-semibold mb-1">
          Candidates ({(plan.candidates || []).length})
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
          {(plan.candidates || []).map((c, i) => (
            <CandidateSummary key={i} candidate={c} index={i} />
          ))}
        </div>
      </section>

      <section>
        <h4 className="text-slate-300 text-sm font-semibold mb-1">
          DOE experiments ({(plan.experiments || []).length})
        </h4>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-800 text-slate-400">
              <tr>
                <th className="py-1 px-2 text-left">ID</th>
                <th className="py-1 px-2 text-left">Kind</th>
                <th className="py-1 px-2">Cand.</th>
                <th className="py-1 px-2">T (K)</th>
                <th className="py-1 px-2">Tier</th>
                <th className="py-1 px-2">Replicas</th>
                <th className="py-1 px-2">Depends</th>
                <th className="py-1 px-2">Action</th>
              </tr>
            </thead>
            <tbody className="text-slate-300">
              {(plan.experiments || []).map((e) => (
                <tr key={e.plan_exp_id} className="border-t border-slate-700/50">
                  <td className="py-1 px-2">{e.plan_exp_id}</td>
                  <td className="py-1 px-2">
                    {e.kind}
                    {e.aggregate?.material ? ` (${e.aggregate.material})` : ''}
                  </td>
                  <td className="py-1 px-2 text-center">{e.candidate_index}</td>
                  <td className="py-1 px-2 text-center">{e.temperature_k}</td>
                  <td className="py-1 px-2 text-center">{e.run_tier || '—'}</td>
                  <td className="py-1 px-2 text-center">{e.replicate_seeds ?? '—'}</td>
                  <td className="py-1 px-2 text-center">{e.depends_on || '—'}</td>
                  <td className="py-1 px-2 text-center">
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs ${
                        e.action === 'reuse'
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : 'bg-sky-500/20 text-sky-300'
                      }`}
                    >
                      {e.action}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {plan.moisture_damage?.enabled && (
        <p className="text-sky-300/80 text-xs">
          Moisture damage track active — wet/dry ER thresholds: warn &lt;{' '}
          {plan.moisture_damage.er_warn_threshold}, fail &lt;{' '}
          {plan.moisture_damage.er_fail_threshold}
        </p>
      )}

      {error && <p className="text-red-400 text-sm">{String(error)}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onBack}
          className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm"
        >
          ← Edit targets
        </button>
        <button
          type="button"
          disabled={approving}
          onClick={onApprove}
          className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-sm font-semibold"
        >
          {approving ? 'Submitting…' : 'Approve & run'}
        </button>
      </div>
    </div>
  )
}

export default DesignPlanReview
