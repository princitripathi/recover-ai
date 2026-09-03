const labels: Record<string, string> = {
  paid: 'Paid',
  failed: 'Failed',
  abandoned: 'Abandoned',
  pending: 'Pending',
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status}`}>{labels[status] || status}</span>;
}
