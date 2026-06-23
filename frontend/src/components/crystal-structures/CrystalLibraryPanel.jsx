import clsx from 'clsx'
import { Loader2, RefreshCw } from 'lucide-react'
import { formatArtifactLabel, formatSizeAngstrom } from './config'

function CrystalLibraryPanel({
  items,
  loading,
  execute,
  selectedCrystalId,
  setSelectedCrystalId,
  selectedCrystals,
  selectedCrystalSet,
  toggleSelectCrystal,
  handleSelectAllCrystals,
}) {
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            className="rounded border-slate-600 bg-slate-800 text-blue-500"
            checked={items.length > 0 && selectedCrystals.length === items.length}
            onChange={(e) => handleSelectAllCrystals(e.target.checked)}
          />
          <h2 className="text-sm font-semibold text-slate-200">Crystal Library ({items.length})</h2>
        </div>
        <button
          type="button"
          className="p-2 rounded bg-slate-700/70 text-slate-200 hover:bg-slate-700"
          onClick={() => execute()}
          title="Refresh"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
        </button>
      </div>

      {items.length === 0 && !loading && (
        <div className="text-sm text-slate-400 py-6 text-center">No crystal structures yet.</div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-700 text-center">
                <th className="w-8 py-2 pr-1"></th>
                <th className="w-8 py-2 pr-1">#</th>
                <th className="py-2 pr-3">Name</th>
                <th className="py-2 pr-3">Material</th>
                <th className="py-2 pr-3">Surface</th>
                <th className="py-2 pr-3">Atoms</th>
                <th className="py-2 pr-3">Size (lx × ly × lz)</th>
                <th className="py-2 pr-3">OH</th>
                <th className="py-2 pr-3">File</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => {
                const lx = item.actual_lx_angstrom || item.xy_size_angstrom || 0
                const ly = item.actual_ly_angstrom || item.xy_size_angstrom || 0
                return (
                  <tr
                    key={item.crystal_id}
                    className={clsx(
                      'border-b border-slate-800 cursor-pointer hover:bg-slate-800/40 text-center',
                      selectedCrystalId === item.crystal_id && 'bg-blue-500/10',
                      selectedCrystalSet.has(item.crystal_id) && 'bg-blue-500/10'
                    )}
                    onClick={() => setSelectedCrystalId(item.crystal_id)}
                  >
                    <td className="py-2 pr-1 w-8">
                      <input
                        type="checkbox"
                        className="rounded border-slate-600 bg-slate-800 text-blue-500"
                        checked={selectedCrystalSet.has(item.crystal_id)}
                        onChange={(e) => toggleSelectCrystal(item.crystal_id, e)}
                      />
                    </td>
                    <td className="py-2 pr-1 text-[10px] text-slate-500 font-mono w-8">{index + 1}</td>
                    <td className="py-2 pr-3 max-w-[220px]" title={item.name}>
                      <div className="font-bold text-slate-200 truncate">
                        {item.name || `${item.material}_${Math.round((lx + ly) / 2)}A_${Math.round(item.thickness_angstrom || 0)}A_${item.surface}`}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {formatSizeAngstrom(lx)}x{formatSizeAngstrom(ly)} h={formatSizeAngstrom(item.thickness_angstrom)} | {Number(item.atom_count || 0).toLocaleString()} atoms
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-slate-300">{item.material}</td>
                    <td className="py-2 pr-3 text-slate-300">{item.surface}</td>
                    <td className="py-2 pr-3 text-slate-200">
                      {Number(item.atom_count || 0).toLocaleString()}
                    </td>
                    <td className="py-2 pr-3 text-[11px] text-slate-400 whitespace-nowrap">
                      <div>
                        {formatSizeAngstrom(lx)} × {formatSizeAngstrom(ly)} × {formatSizeAngstrom(item.thickness_angstrom)} A
                        {item.anisotropy_pct != null && item.anisotropy_pct > 0.1 && (
                          <span className="ml-1 text-amber-400/70">
                            ({Number(item.anisotropy_pct).toFixed(1)}%)
                          </span>
                        )}
                      </div>
                      {item.metadata?.target_thickness_angstrom != null && (
                        <div className="text-[10px] text-slate-500">
                          target th: {Number(item.metadata.target_thickness_angstrom).toFixed(1)} A
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-[11px] text-slate-400 whitespace-nowrap">
                      {item.hydroxylated
                        ? <span className="text-emerald-400/80">{Number(item.hydroxyl_density || 0).toFixed(1)}/nm²</span>
                        : <span className="text-slate-500">bare</span>}
                    </td>
                    <td className="py-2 pr-3 text-[10px] text-slate-500 whitespace-nowrap max-w-[120px] truncate"
                      title={item.lammps_data_file_path || ''}>
                      {formatArtifactLabel(item.lammps_data_file_path)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default CrystalLibraryPanel
