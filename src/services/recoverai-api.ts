export type DashboardSummary = {
  total_transactions: number;
  revenue_processed: string;
  revenue_at_risk: string;
  failed_transaction_count: number;
  abandoned_transaction_count: number;
  recovery_cases: number;
  revenue_recovered: string;
  recovery_rate: number;
  cases_to_review: number;
};

export type Transaction = {
  id: string;
  customer_id: string;
  customer_name: string;
  amount: string;
  currency: string;
  status: 'paid' | 'failed' | 'abandoned' | 'pending';
  payment_method: string;
  failure_reason: string | null;
  created_at: string;
  is_revenue_at_risk: boolean;
};

export type RecoveryCase = {
  id: string;
  transaction_id: string;
  customer_name: string | null;
  amount: string | null;
  currency: string | null;
  transaction_status: Transaction['status'];
  failure_reason: string | null;
  risk_score: number;
  root_cause: string | null;
  recommended_action: string | null;
  confidence: number | null;
  status: string;
  amount_recovered: string;
  created_at: string;
};

type Health = {
  status: string;
  service: string;
  mode: string;
};

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const recoverAiApi = {
  getHealth: () => request<Health>('/api/health'),
  getSummary: () => request<DashboardSummary>('/api/dashboard/summary'),
  getTransactions: () => request<Transaction[]>('/api/transactions'),
  getTransaction: (id: string) => request<Transaction>(`/api/transactions/${encodeURIComponent(id)}`),
  getRecoveryCases: () => request<RecoveryCase[]>('/api/recovery-cases'),
};
