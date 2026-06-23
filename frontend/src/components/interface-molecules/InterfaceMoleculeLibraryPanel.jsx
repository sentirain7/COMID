import clsx from 'clsx'
import { Loader2, RefreshCw } from 'lucide-react'
import { INTERFACE_MOLECULE_INFO } from './config'

function InterfaceMoleculeLibraryPanel({
  cells,
  loading,
  execute,
  selectedCellId,
  setSelectedCellId,
  selectedCells,
  selectedCellSet,
  toggleSelectCell,
  handleSelectAllCells,
}) {
  const allSelected = cells.length > 0 && selectedCells.length === cells.length

  return (
    <div className="card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            className="rounded border-slate-600 bg-slate-800 text-blue-500"
            checked={allSelected}
            onChange={(e) => handleSelectAllCells(e.target.checked)}
          />
          <h2 className="text-sm font-semibold text-slate-200">Interface Cell Library ({cells.length})</h2>
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

      {cells.length === 0 && !loading && (
        <div className="text-sm text-slate-400 py-6 text-center">No interface cells in library</div>
      )}

      {cells.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-700 text-center">
                <th className="w-8 py-2 pr-1"></th>
                <th className="w-8 py-2 pr-1">#</th>
                <th className="py-2 pr-3">Name</th>
                <th className="py-2 pr-3">Molecule</th>
                <th className="py-2 pr-3">Density</th>
                <th className="py-2 pr-3">Box Size</th>
                <th className="py-2 pr-3">Atoms</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    <Loader2 className="w-5 h-5 animate-spin inline" />
                  </td>
                </tr>
              ) : (
                cells.map((cell, index) => {
                  const molInfo = INTERFACE_MOLECULE_INFO[cell.mol_id] || {}
                  const isSelected = selectedCellId === cell.cell_id
                  const isChecked = selectedCellSet.has(cell.cell_id)
                  return (
                    <tr
                      key={cell.cell_id}
                      className={clsx(
                        'border-b border-slate-800 cursor-pointer hover:bg-slate-800/40 text-center',
                        isSelected && 'bg-blue-500/10',
                        isChecked && 'bg-blue-500/10'
                      )}
                      onClick={() => setSelectedCellId(cell.cell_id)}
                    >
                      <td className="py-2 pr-1 w-8">
                        <input
                          type="checkbox"
                          className="rounded border-slate-600 bg-slate-800 text-blue-500"
                          checked={isChecked}
                          onChange={(e) => toggleSelectCell(cell.cell_id, e)}
                        />
                      </td>
                      <td className="py-2 pr-1 text-[10px] text-slate-500 font-mono w-8">{index + 1}</td>
                      <td className="py-2 pr-3 max-w-[220px]" title={cell.name}>
                        <div className="font-bold text-slate-200 truncate">
                          {cell.name}
                        </div>
                        <div className="text-[10px] text-slate-500">
                          {cell.mol_id}
                        </div>
                      </td>
                      <td className="py-2 pr-3 text-slate-300">{molInfo.formula || cell.mol_id}</td>
                      <td className="py-2 pr-3 text-slate-400">
                        {(cell.actual_density || cell.target_density || 0).toFixed(2)}
                      </td>
                      <td className="py-2 pr-3 text-[11px] text-slate-400 whitespace-nowrap">
                        {cell.lx_angstrom?.toFixed(0)} x {cell.ly_angstrom?.toFixed(0)} x {cell.lz_angstrom?.toFixed(0)} A
                      </td>
                      <td className="py-2 pr-3 text-slate-200">
                        {cell.atom_count?.toLocaleString()}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default InterfaceMoleculeLibraryPanel
