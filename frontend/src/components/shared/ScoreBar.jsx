function ScoreBar({ score, maxScore = 1.0, label }) {
  const pct = Math.min(100, Math.max(0, (score / maxScore) * 100))
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-1.5">
      {label && <span className="text-slate-400 text-xs">{label}</span>}
      <div className="w-16 h-1.5 bg-slate-600 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-slate-300 text-xs">{score?.toFixed(2) || '-'}</span>
    </div>
  )
}

export default ScoreBar
