export const toErrorMessage = (err) =>
  err?.response?.data?.detail || err?.message || 'Unknown error'

export const wrapQuery = (query) => ({
  data: query.data ?? null,
  loading: query.isLoading,
  error: query.error ? toErrorMessage(query.error) : null,
  execute: query.refetch,
})
