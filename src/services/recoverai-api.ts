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
  retry_count: number;
  previous_successful_payments: number;
  customer_lifetime_value: string;
  hours_since_event: number;
  checkout_session_id: string | null;
};

export type RecoveryCase = {
  id: string;
  transaction_id: string;
  customer_name: string | null;
  amount: string | null;
  currency: string | null;
  transaction_status: Transaction['status'];
  failure_reason: string | null;
  retry_count: number | null;
  previous_successful_payments: number | null;
  customer_lifetime_value: string | null;
  hours_since_event: number | null;
  risk_score: number;
  risk_level: string;
  risk_factors: string;
  recovery_priority: number;
  root_cause: string | null;
  recommended_action: string | null;
  confidence: number | null;
  diagnosis_reason: string | null;
  diagnosis_status: string;
  diagnosed_at: string | null;
  status: string;
  amount_recovered: string;
  created_at: string;
};

export type RiskSummary = {
  total_risk_cases: number;
  high_risk_cases: number;
  medium_risk_cases: number;
  low_risk_cases: number;
  revenue_at_risk: string;
  high_risk_revenue: string;
  medium_risk_revenue: string;
  low_risk_revenue: string;
  average_risk_score: number;
  recovery_priority_high: number;
};

export type DiagnosisResult = {
  diagnosis_status: string;
  case_id: string;
  root_cause?: string;
  recommended_action?: string;
  confidence?: number;
  reason?: string;
  risk_factors?: string[];
  diagnosed_at?: string;
  error?: string;
};

export type RuleEvaluation = {
  rule: string;
  passed: boolean;
  detail: string;
};

export type PolicyResult = {
  decision: string;
  case_id: string;
  action: string;
  reason: string;
  rules_evaluated: RuleEvaluation[];
  policy_version: string;
  evaluated_at: string;
};

export type ExecutionResult = {
  case_id: string;
  action: string;
  execution_status: string;
  policy_decision: string;
  policy_decision_id?: number | null;
  razorpay_called: boolean;
  razorpay_reference?: string | null;
  payment_link_id?: string | null;
  payment_link_url?: string | null;
  message: string;
  created_at: string;
};

export type ExecutionHistoryItem = {
  id: number;
  case_id: string;
  action: string;
  execution_status: string;
  razorpay_reference?: string | null;
  payment_link_url?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
};

export type EvaluationResult = {
  evaluation_type: string;
  dataset_size: number;
  total_transactions?: number;
  total_revenue?: string;
  revenue_at_risk: string;
  recovery_cases?: number;
  eligible_cases?: number;
  policy_allowed: number;
  policy_blocked: number;
  recovery_attempts: number;
  successful_recoveries: number;
  failed_recoveries?: number;
  amount_recovered: string;
  recovery_rate: number;
  case_recovery_rate: number;
  baseline_recovered?: string;
  baseline_note?: string;
  created_at?: string;
  id?: number;
  details?: unknown;
};

type Health = {
  status: string;
  service: string;
  mode: string;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...options });
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
  getRiskCases: (params?: { risk_level?: string; sort_by?: string; order?: string }) => {
    const query = new URLSearchParams();
    if (params?.risk_level) query.set('risk_level', params.risk_level);
    if (params?.sort_by) query.set('sort_by', params.sort_by);
    if (params?.order) query.set('order', params.order);
    const qs = query.toString();
    return request<RecoveryCase[]>(`/api/risk/cases${qs ? `?${qs}` : ''}`);
  },
  getRiskCase: (id: string) => request<RecoveryCase>(`/api/risk/cases/${encodeURIComponent(id)}`),
  getRiskSummary: () => request<RiskSummary>('/api/risk/summary'),
  runDiagnosis: (caseId: string) =>
    request<DiagnosisResult>(`/api/recovery-cases/${encodeURIComponent(caseId)}/diagnose`, {
      method: 'POST',
    }),
  getDiagnosis: (caseId: string) =>
    request<DiagnosisResult>(`/api/recovery-cases/${encodeURIComponent(caseId)}/diagnosis`),
  runPolicyCheck: (caseId: string) =>
    request<PolicyResult>(`/api/recovery-cases/${encodeURIComponent(caseId)}/policy-check`, {
      method: 'POST',
    }),
  getPolicyDecision: (caseId: string) =>
    request<PolicyResult>(`/api/recovery-cases/${encodeURIComponent(caseId)}/policy`),
  executeRecoveryAction: (caseId: string, action: string) =>
    request<ExecutionResult>(`/api/recovery-cases/${encodeURIComponent(caseId)}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    }),
  getExecutionHistory: (caseId: string) =>
    request<{ case_id: string; actions: ExecutionHistoryItem[] }>(
      `/api/recovery-cases/${encodeURIComponent(caseId)}/actions`
    ),
  runEvaluation: () =>
    request<EvaluationResult>(`/api/evaluation/run`, { method: 'POST' }),
  getLatestEvaluation: () =>
    request<EvaluationResult>(`/api/evaluation/latest`),
  getWebhookEvents: () =>
    request<{ events: unknown[] }>(`/api/webhooks/events`),
};
