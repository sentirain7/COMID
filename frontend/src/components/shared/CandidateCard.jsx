import { CANDIDATE_ORIGIN_COLORS } from '../../lib/constants'
import ScoreBar from './ScoreBar'

function CandidateCard({ candidate, rank }) {
  const originClass = CANDIDATE_ORIGIN_COLORS[candidate.origin] || 'bg-slate-600 text-slate-200'
  return (
    <div className="bg-slate-700/30 rounded p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-slate-200">
          {rank != null && <span className="text-slate-400 mr-1">#{rank + 1}</span>}
          {candidate.additive_type || 'Base mixture'}
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-1.5 py-0.5 rounded text-xs ${originClass}`}>
            {candidate.origin || 'unknown'}
          </span>
          {candidate.score != null && (
            <ScoreBar score={candidate.score} />
          )}
        </div>
      </div>
      {(candidate.recommended_wt_pct_min > 0 || candidate.recommended_wt_pct_max > 0) && (
        <div className="text-slate-400 mt-1">
          {candidate.recommended_wt_pct_min?.toFixed(1)} ~ {candidate.recommended_wt_pct_max?.toFixed(1)} wt%
        </div>
      )}
      {candidate.wt_pct != null && (
        <div className="text-slate-400 mt-1">
          {candidate.wt_pct?.toFixed(1)} wt%
        </div>
      )}
      {candidate.rationale && (
        <details className="mt-1">
          <summary className="text-slate-400 cursor-pointer">Rationale</summary>
          <p className="text-slate-300 mt-1 pl-2">{candidate.rationale}</p>
        </details>
      )}
    </div>
  )
}

export default CandidateCard
