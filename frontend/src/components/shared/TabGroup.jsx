import { useId } from 'react'

function TabGroup({ tabs, activeTab, onTabChange }) {
  const prefix = useId()

  const handleKeyDown = (e, index) => {
    let nextIndex
    if (e.key === 'ArrowRight') {
      nextIndex = (index + 1) % tabs.length
    } else if (e.key === 'ArrowLeft') {
      nextIndex = (index - 1 + tabs.length) % tabs.length
    } else {
      return
    }
    e.preventDefault()
    onTabChange(tabs[nextIndex].key)
    document.getElementById(`${prefix}-tab-${tabs[nextIndex].key}`)?.focus()
  }

  return (
    <div className="flex gap-1 border-b border-slate-700 mb-3" role="tablist">
      {tabs.map((tab, index) => (
        <button
          key={tab.key}
          id={`${prefix}-tab-${tab.key}`}
          role="tab"
          aria-selected={activeTab === tab.key}
          tabIndex={activeTab === tab.key ? 0 : -1}
          onClick={() => onTabChange(tab.key)}
          onKeyDown={(e) => handleKeyDown(e, index)}
          className={`px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
            activeTab === tab.key
              ? 'bg-slate-700 text-white border-b-2 border-blue-500'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export default TabGroup
