const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path) {
  const response = await fetch(`${API_BASE_URL}${path}`)
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `Request failed with status ${response.status}`)
  }
  return response.json()
}

export const api = {
  getSummary: () => request('/api/dashboard/summary'),
  getTransactions: () => request('/api/transactions'),
  getTransaction: (id) => request(`/api/transactions/${encodeURIComponent(id)}`),
  getRecoveryCases: () => request('/api/recovery-cases'),
}
