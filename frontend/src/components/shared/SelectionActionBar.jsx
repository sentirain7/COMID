function SelectionActionBar({ count, actions, onDeselect }) {
  if (!count) return null

  return (
    <div className="fixed bottom-0 left-72 right-0 z-40 flex items-center gap-3 px-4 py-2.5 bg-slate-800 border-t border-slate-700">
      <span className="text-xs text-slate-300">{count} selected</span>
      {actions}
      <button
        onClick={onDeselect}
        className="px-2 py-1 rounded text-xs text-slate-400 hover:text-slate-200"
      >
        Clear
      </button>
    </div>
  )
}

export default SelectionActionBar
