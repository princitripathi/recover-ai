type KpiCardProps = {
  label: string;
  value: string | number;
  helper: string;
  tone?: 'neutral' | 'risk' | 'review';
};

export function KpiCard({ label, value, helper, tone = 'neutral' }: KpiCardProps) {
  return (
    <article className={`kpi-card ${tone}`}>
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{helper}</span>
    </article>
  );
}
