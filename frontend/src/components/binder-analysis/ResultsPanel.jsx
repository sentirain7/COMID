import { useState } from 'react'
import { TabGroup } from '../shared'
import ResultsChart from './ResultsChart'

const TABS = [
  { key: 'table', label: 'Metrics Table' },
  { key: 'charts', label: 'Charts' },
]

function ResultsPanel({ results = [], loading }) {
  const [activeTab, setActiveTab] = useState('table')

  if (loading) {
    return <p className="text-sm text-slate-400">Loading results...</p>
  }

  if (results.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-6 text-center text-sm text-slate-400">
        No completed results yet.
      </div>
    )
  }

  const allMetrics = new Set()
  for (const r of results) {
    for (const k of Object.keys(r.metrics || {})) {
      allMetrics.add(k)
    }
  }
  const metricKeys = Array.from(allMetrics)

  return (
    <div>
      <TabGroup tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab} />

      {activeTab === 'table' && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-center">
            <thead className="sticky top-0 bg-slate-800 border-b border-slate-700/50">
              <tr className="text-slate-400">
                <th className="px-3 py-2 font-medium">Run Key</th>
                <th className="px-3 py-2 font-medium">Temp (K)</th>
                {metricKeys.map((key) => (
                  <th key={key} className="px-3 py-2 font-medium">{key}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {results.map((r) => (
                <tr key={r.run_key} className="hover:bg-slate-700/30 transition-colors text-center">
                  <td className="px-3 py-2 font-mono text-slate-200 truncate max-w-[140px]">
                    {r.run_key}
                  </td>
                  <td className="px-3 py-2 text-slate-300">
                    {r.temperature_K != null ? `${r.temperature_K}` : '-'}
                  </td>
                  {metricKeys.map((key) => {
                    const m = r.metrics?.[key]
                    return (
                      <td key={key} className="px-3 py-2 text-slate-300">
                        {m ? `${Number(m.value).toFixed(4)}${m.unit ? ` ${m.unit}` : ''}` : '-'}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'charts' && (
        <div className="card p-4">
          <ResultsChart results={results} />
        </div>
      )}
    </div>
  )
}

export default ResultsPanel
