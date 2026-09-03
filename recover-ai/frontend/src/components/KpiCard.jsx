export function KpiCard({ label, value, helper, tone = 'neutral' }) {
  return (
    <article className={`kpi-card ${tone}`}>
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{helper}</span>
    </article>
  )
}
