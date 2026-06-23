/**
 * Force Field Filter Component
 * Provides tabbed view for bulk_ff_gaff2 (default) and reaxff data
 */
function FFFilter({ selected, onChange }) {
  const options = [
    {
      id: 'bulk_ff_gaff2',
      label: 'GAFF2',
      description: 'GAFF2 based simulations',
      icon: '⚡',
      color: 'blue'
    },
    {
      id: 'reaxff',
      label: 'ReaxFF',
      description: 'Reactive validation runs',
      icon: '🔬',
      color: 'orange'
    }
  ]

  const getButtonClasses = (option) => {
    const isSelected = selected === option.id
    const colorClasses = {
      blue: isSelected
        ? 'bg-blue-600 border-blue-500 text-white'
        : 'bg-slate-700 border-slate-600 text-slate-300 hover:bg-slate-600',
      orange: isSelected
        ? 'bg-orange-600 border-orange-500 text-white'
        : 'bg-slate-700 border-slate-600 text-slate-300 hover:bg-slate-600',
    }
    return colorClasses[option.color]
  }

  return (
    <div className="flex gap-2 p-1 bg-slate-800 rounded-lg border border-slate-700">
      {options.map((option) => (
        <button
          key={option.id}
          onClick={() => onChange(option.id)}
          className={`
            flex items-center gap-2 px-4 py-2 rounded-md border
            transition-all duration-200
            ${getButtonClasses(option)}
          `}
        >
          <span className="text-lg">{option.icon}</span>
          <div className="text-left">
            <div className="font-medium text-sm">{option.label}</div>
            <div className="text-xs opacity-75">{option.description}</div>
          </div>
        </button>
      ))}
    </div>
  )
}

/**
 * Compact version for header/toolbar
 */
export function FFFilterCompact({ selected, onChange }) {
  return (
    <div className="flex bg-slate-700 rounded-lg p-0.5">
      <button
        onClick={() => onChange('bulk_ff_gaff2')}
        className={`px-3 py-1 text-sm rounded-md transition-colors ${
          selected === 'bulk_ff_gaff2'
            ? 'bg-blue-600 text-white'
            : 'text-slate-300 hover:text-white'
        }`}
      >
        GAFF2
      </button>
      <button
        onClick={() => onChange('reaxff')}
        className={`px-3 py-1 text-sm rounded-md transition-colors ${
          selected === 'reaxff'
            ? 'bg-orange-600 text-white'
            : 'text-slate-300 hover:text-white'
        }`}
      >
        ReaxFF
      </button>
    </div>
  )
}

/**
 * Badge showing current filter
 */
export function FFFilterBadge({ ffType }) {
  const isReaxFF = ffType === 'reaxff'

  return (
    <span
      className={`
        inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium
        ${isReaxFF ? 'bg-orange-900/50 text-orange-300' : 'bg-blue-900/50 text-blue-300'}
      `}
    >
      {isReaxFF ? '🔬' : '⚡'}
      {isReaxFF ? 'ReaxFF' : 'GAFF2'}
    </span>
  )
}

export default FFFilter
