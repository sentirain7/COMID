function CompositionTable({ molCounts, molDetails, totalMass }) {
  if (!molCounts || Object.keys(molCounts).length === 0) {
    return (
      <p className="text-red-400 text-sm font-medium">
        ERROR: experiment_molecules missing
      </p>
    )
  }

  const total = Object.values(molCounts).reduce((sum, count) => sum + count, 0)
  const entries = Object.entries(molCounts).sort((a, b) => {
    if (molDetails) {
      const weightA = molDetails[a[0]]?.weight || 0
      const weightB = molDetails[b[0]]?.weight || 0
      return weightB - weightA
    }
    return b[1] - a[1]
  })

  const hasMolDetails = molDetails && Object.keys(molDetails).length > 0

  return (
    <div className="max-h-48 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-slate-800">
          <tr className="text-slate-400 text-center">
            <th className="py-1 px-2">Molecule</th>
            <th className="py-1 px-2">Count</th>
            {hasMolDetails && (
              <>
                <th className="py-1 px-2">MW</th>
                <th className="py-1 px-2">Weight</th>
              </>
            )}
            <th className="py-1 px-2">wt%</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([molId, count]) => {
            const detail = molDetails?.[molId]
            const weight = detail?.weight || 0
            const mw = detail?.molecular_weight || 0
            const wtPercent = totalMass > 0 ? (weight / totalMass) * 100 : (count / total) * 100
            return (
              <tr key={molId} className="border-t border-slate-700/50 text-center">
                <td className="py-1 px-2 text-slate-300 font-mono text-xs" title={molId}>
                  {detail?.short_name || molId}
                </td>
                <td className="py-1 px-2 text-white">{count}</td>
                {hasMolDetails && (
                  <>
                    <td className="py-1 px-2 text-slate-400">{mw.toFixed(1)}</td>
                    <td className="py-1 px-2 text-slate-400">{weight.toFixed(0)}</td>
                  </>
                )}
                <td className="py-1 px-2 text-slate-400">
                  {wtPercent.toFixed(1)}%
                </td>
              </tr>
            )
          })}
          <tr className="border-t-2 border-slate-600 font-semibold text-center">
            <td className="py-1 px-2 text-slate-300">Total</td>
            <td className="py-1 px-2 text-white">{total}</td>
            {hasMolDetails && (
              <>
                <td className="py-1 px-2 text-slate-400">-</td>
                <td className="py-1 px-2 text-white">
                  {totalMass ? totalMass.toFixed(0) : '-'}
                </td>
              </>
            )}
            <td className="py-1 px-2 text-slate-400">100%</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export default CompositionTable
