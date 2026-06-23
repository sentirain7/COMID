function MetricsTable({ metrics }) {
  const metricDefs = [
    { key: 'density', label: 'Density', unit: 'g/cm³', format: (v) => v?.toFixed(4) },
    { key: 'cohesive_energy_density', label: 'CED', unit: 'MJ/m³', format: (v) => v?.toFixed(2) },
    { key: 'total_energy', label: 'Total Energy', unit: 'kcal/mol', format: (v) => v != null ? `${(v / 1000).toFixed(1)}k` : null },
    { key: 'potential_energy', label: 'Potential Energy', unit: 'kcal/mol', format: (v) => v != null ? `${(v / 1000).toFixed(1)}k` : null },
    { key: 'kinetic_energy', label: 'Kinetic Energy', unit: 'kcal/mol', format: (v) => v != null ? `${(v / 1000).toFixed(1)}k` : null },
    { key: 'potential_energy_density', label: 'PE Density', unit: 'kcal/mol/Å³', format: (v) => v?.toExponential(3) },
    { key: 'kinetic_energy_density', label: 'KE Density', unit: 'kcal/mol/Å³', format: (v) => v?.toExponential(3) },
    { key: 'total_energy_density', label: 'TE Density', unit: 'kcal/mol/Å³', format: (v) => v?.toExponential(3) },
  ]

  const hasAnyMetric = metricDefs.some((m) => metrics?.[m.key] != null)

  if (!hasAnyMetric) {
    return <p className="text-slate-400 text-sm">No metric data available</p>
  }

  return (
    <div className="max-h-48 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-slate-800">
          <tr className="text-slate-400 text-center">
            <th className="py-1 px-2">Metric</th>
            <th className="py-1 px-2">Value</th>
            <th className="py-1 px-2">Unit</th>
          </tr>
        </thead>
        <tbody>
          {metricDefs.map(({ key, label, unit, format }) => {
            const value = metrics?.[key]
            const formattedValue = value != null ? format(value) : '-'
            return (
              <tr key={key} className="border-t border-slate-700/50 text-center">
                <td className="py-1 px-2 text-slate-300">{label}</td>
                <td className="py-1 px-2 text-white font-mono">{formattedValue}</td>
                <td className="py-1 px-2 text-slate-400 text-xs">{unit}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default MetricsTable
