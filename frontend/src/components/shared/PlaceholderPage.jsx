function PlaceholderPage({ title, description, purposeTitle = 'Purpose', purposeItems = [], emptyTitle, emptyMessage }) {
  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-white">{title}</h1>
        {description && (
          <p className="text-sm text-slate-400 mt-1">
            {description}
          </p>
        )}
      </div>

      <div className="card p-4">
        <h2 className="text-sm font-semibold text-slate-300 mb-2">{purposeTitle}</h2>
        <ul className="text-sm text-slate-400 space-y-1">
          {purposeItems.map((item) => (
            <li key={item}>- {item}</li>
          ))}
        </ul>
      </div>

      <div className="card p-4">
        <h2 className="text-sm font-semibold text-slate-300 mb-2">{emptyTitle}</h2>
        <div className="text-sm text-slate-500">
          {emptyMessage}
        </div>
      </div>
    </div>
  )
}

export default PlaceholderPage
