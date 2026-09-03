'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BadgeIndianRupee, FileSearch, ShieldCheck } from 'lucide-react';
import { KpiCard } from '@/components/recoverai/KpiCard';
import { ErrorState, LoadingState } from '@/components/recoverai/States';
import { StatusBadge } from '@/components/recoverai/StatusBadge';
import { recoverAiApi, type DashboardSummary, type RecoveryCase, type Transaction } from '@/services/recoverai-api';

const money = (value: string | number | null | undefined, currency = 'INR') => new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency,
  maximumFractionDigits: 0,
}).format(Number(value || 0));

const formatDate = (value: string) => new Intl.DateTimeFormat('en-IN', {
  dateStyle: 'medium',
  timeStyle: 'short',
}).format(new Date(value));

function RiskBar({ value }: { value: number }) {
  return (
    <div className="risk-bar">
      <span style={{ width: `${value}%` }} />
      <b>{value}</b>
    </div>
  );
}

function TransactionDetail({ transaction }: { transaction: Transaction | null }) {
  if (!transaction) {
    return <aside className="detail-card empty-detail">Select a recovery case to inspect the linked transaction.</aside>;
  }

  return (
    <aside className="detail-card">
      <div>
        <p className="eyebrow">Transaction Detail</p>
        <h3>{transaction.id}</h3>
      </div>
      <dl>
        <div><dt>Customer</dt><dd>{transaction.customer_name}</dd></div>
        <div><dt>Amount</dt><dd>{money(transaction.amount, transaction.currency)}</dd></div>
        <div><dt>Status</dt><dd><StatusBadge status={transaction.status} /></dd></div>
        <div><dt>Payment method</dt><dd>{transaction.payment_method}</dd></div>
        <div><dt>Failure reason</dt><dd>{transaction.failure_reason || 'Not applicable'}</dd></div>
        <div><dt>Timestamp</dt><dd>{formatDate(transaction.created_at)}</dd></div>
        <div><dt>Revenue at risk</dt><dd>{transaction.is_revenue_at_risk ? 'Yes' : 'No'}</dd></div>
      </dl>
    </aside>
  );
}

export default function Home() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [apiMode, setApiMode] = useState('checking');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      recoverAiApi.getHealth(),
      recoverAiApi.getSummary(),
      recoverAiApi.getRecoveryCases(),
      recoverAiApi.getTransactions(),
    ])
      .then(([health, summaryData, caseData, transactionData]) => {
        setApiMode(health.mode);
        setSummary(summaryData);
        setCases(caseData);
        setTransactions(transactionData);
        setSelectedId(caseData[0]?.transaction_id || transactionData[0]?.id || null);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const selectedTransaction = useMemo(
    () => transactions.find((item) => item.id === selectedId) || null,
    [transactions, selectedId],
  );

  if (loading) return <LoadingState />;
  if (error || !summary) return <ErrorState message={error || 'Dashboard summary was not returned.'} />;

  const riskCaseCount = summary.failed_transaction_count + summary.abandoned_transaction_count;
  const failedShare = riskCaseCount > 0 ? Math.round((summary.failed_transaction_count / riskCaseCount) * 100) : 0;

  return (
    <main className="dashboard-shell">
      <header className="hero-card">
        <div className="brand-mark">RA</div>
        <div>
          <p className="eyebrow">Revenue Recovery Intelligence</p>
          <h1>RecoverAI</h1>
          <span className="demo-pill">Demo Mode - {apiMode.replace('-', ' ')}</span>
        </div>
      </header>

      <section className="kpi-grid" aria-label="Key revenue recovery metrics">
        <KpiCard tone="risk" label="Revenue at Risk" value={money(summary.revenue_at_risk)} helper={`${summary.failed_transaction_count} failed, ${summary.abandoned_transaction_count} abandoned`} />
        <KpiCard label="Revenue Recovered" value={money(summary.revenue_recovered)} helper="Recovery execution not enabled" />
        <KpiCard label="Recovery Rate" value={`${summary.recovery_rate}%`} helper="Deterministic baseline" />
        <KpiCard tone="review" label="Cases to Review" value={summary.cases_to_review} helper={`${summary.total_transactions} total transactions`} />
      </section>

      <section className="overview-grid">
        <article className="panel revenue-panel">
          <div className="section-heading"><BadgeIndianRupee size={20} /><h2>Revenue Overview</h2></div>
          <p className="large-number">{money(summary.revenue_at_risk)}</p>
          <p className="muted">Revenue at risk is calculated from failed and abandoned transactions returned by the FastAPI backend.</p>
          <div className="stacked-bar" aria-label="Risk composition"><span className="failed" style={{ width: `${failedShare}%` }} /><span className="abandoned" /></div>
          <div className="legend"><span><i className="dot failed" />Failed</span><span><i className="dot abandoned" />Abandoned</span></div>
        </article>
        <article className="panel readiness-panel">
          <div className="section-heading"><ShieldCheck size={20} /><h2>Foundation Boundaries</h2></div>
          <ul>
            <li>Dashboard reads from FastAPI and SQLite-backed synthetic data.</li>
            <li>Revenue risk remains deterministic for this stage.</li>
            <li>AI diagnosis fields are intentionally not displayed as responses.</li>
            <li>Razorpay, auth, and recovery execution are not implemented yet.</li>
          </ul>
        </article>
      </section>

      <section className="workspace-grid">
        <article className="panel table-panel">
          <div className="section-heading"><FileSearch size={20} /><h2>Recovery Cases</h2></div>
          {cases.length === 0 ? <div className="empty-row">No failed or abandoned transactions need review.</div> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Case / Transaction</th><th>Customer</th><th>Amount</th><th>Status</th><th>Failure Reason</th><th>Risk</th><th>Created At</th></tr></thead>
                <tbody>
                  {cases.map((item) => (
                    <tr key={item.id} onClick={() => setSelectedId(item.transaction_id)} className={selectedId === item.transaction_id ? 'selected' : ''}>
                      <td><strong>{item.id}</strong><span>{item.transaction_id}</span></td>
                      <td>{item.customer_name}</td>
                      <td>{money(item.amount, item.currency || 'INR')}</td>
                      <td><StatusBadge status={item.transaction_status} /></td>
                      <td>{item.failure_reason || 'Not provided'}</td>
                      <td><RiskBar value={item.risk_score} /></td>
                      <td>{formatDate(item.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
        <TransactionDetail transaction={selectedTransaction} />
      </section>

      <footer className="demo-note"><AlertTriangle size={16} /> This preview uses deterministic synthetic demo data through the FastAPI backend.</footer>
    </main>
  );
}
