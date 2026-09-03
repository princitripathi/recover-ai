const labels = {
  paid: 'Paid',
  failed: 'Failed',
  abandoned: 'Abandoned',
  pending: 'Pending',
}

export function StatusBadge({ status }) {
  return <span className={`status-badge status-${status}`}>{labels[status] || status}</span>
}
