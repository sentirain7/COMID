function DeleteModal({
  isOpen,
  title = 'Delete Experiment?',
  description,
  confirmLabel = 'Delete',
  expId,
  onClose,
  onConfirm,
}) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="card p-6 max-w-md mx-4">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="text-slate-400 mt-2">
          {description || (
            <>
              This will permanently delete <code className="text-blue-400">{expId}</code> and all associated data.
            </>
          )}
        </p>
        <div className="flex gap-3 mt-6 justify-end">
          <button onClick={onClose} className="btn btn-secondary">Cancel</button>
          <button onClick={onConfirm} className="btn bg-red-600 hover:bg-red-700 text-white">{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}

export default DeleteModal
