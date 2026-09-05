'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BadgeIndianRupee, FileSearch, ShieldCheck, Sparkles, Loader2, Zap } from 'lucide-react';
import { KpiCard } from '@/components/recoverai/KpiCard';
import { ErrorState, LoadingState } from '@/components/recoverai/States';
import { StatusBadge } from '@/components/recoverai/StatusBadge';
import {
  recoverAiApi,
  type DashboardSummary,
  type RecoveryCase,
  type Transaction,
  type RiskSummary,
  type DiagnosisResult,
  type PolicyResult,
  type ExecutionResult,
  type ExecutionHistoryItem,
} from '@/services/recoverai-api';

const money = (value: string | number | null | undefined, currency = 'INR') =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value || 0));

const formatDate = (value: string) =>
  new Intl.DateTimeFormat('en-IN', {
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

function RiskLevelBadge({ level }: { level: string }) {
  const cls =
    level === 'HIGH' ? 'risk-badge risk-high' :
    level === 'MEDIUM' ? 'risk-badge risk-medium' :
    'risk-badge risk-low';
  return <span className={cls}>{level}</span>;
}

function PriorityBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="priority-bar">
      <span className="priority-fill" style={{ width: `${pct}%` }} />
      <b>{pct}%</b>
    </div>
  );
}

function parseRiskFactors(factorsJson: string): string[] {
  try {
    const parsed = JSON.parse(factorsJson);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function RiskFactorsList({ factorsJson }: { factorsJson: string }) {
  const factors = parseRiskFactors(factorsJson);
  if (factors.length === 0) return <span className="muted">No factors recorded</span>;
  return (
    <ul className="risk-factors-list">
      {factors.map((f, i) => <li key={i}>{f}</li>)}
    </ul>
  );
}

function DiagnosisSection({
  riskCase,
  diagnosis,
  diagnosisLoading,
  diagnosisError,
  onRunDiagnosis,
}: {
  riskCase: RecoveryCase | null;
  diagnosis: DiagnosisResult | null;
  diagnosisLoading: boolean;
  diagnosisError: string | null;
  onRunDiagnosis: () => void;
}) {
  if (!riskCase) return null;

  const status = diagnosis?.diagnosis_status || riskCase.diagnosis_status;
  const isPending = status === 'pending';
  const isCompleted = status === 'completed';
  const isUnavailable = status === 'ai_unavailable';
  const isParseError = status === 'parse_error';

  const rootCause = diagnosis?.root_cause || riskCase.root_cause;
  const action = diagnosis?.recommended_action || riskCase.recommended_action;
  const confidence = diagnosis?.confidence ?? riskCase.confidence;
  const reason = diagnosis?.reason || riskCase.diagnosis_reason;
  const diagFactors = diagnosis?.risk_factors || [];
  const diagFactorsJson = diagFactors.length > 0 ? JSON.stringify(diagFactors) : riskCase.risk_factors;

  return (
    <>
      <div className="detail-divider" />
      <div className="ai-diagnosis-header">
        <p className="eyebrow"><Sparkles size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />AI Diagnosis</p>
        {isPending && (
          <button className="diagnose-btn" onClick={onRunDiagnosis} disabled={diagnosisLoading}>
            {diagnosisLoading ? <><Loader2 size={14} className="spin" /> Diagnosing...</> : 'Run AI Diagnosis'}
          </button>
        )}
      </div>

      {diagnosisLoading && (
        <div className="diagnosis-status-card">
          <Loader2 size={18} className="spin" />
          <span>Running AI diagnosis...</span>
        </div>
      )}

      {diagnosisError && (
        <div className="diagnosis-status-card diagnosis-error">
          <span>{diagnosisError}</span>
        </div>
      )}

      {isUnavailable && !diagnosisLoading && (
        <div className="diagnosis-status-card diagnosis-unavailable">
          <span>AI service unavailable. Diagnosis requires a running Ollama instance.</span>
          <button className="diagnose-btn retry-btn" onClick={onRunDiagnosis} disabled={diagnosisLoading}>Retry</button>
        </div>
      )}

      {isParseError && !diagnosisLoading && (
        <div className="diagnosis-status-card diagnosis-unavailable">
          <span>AI returned an invalid response. Try again.</span>
          <button className="diagnose-btn retry-btn" onClick={onRunDiagnosis} disabled={diagnosisLoading}>Retry</button>
        </div>
      )}

      {isCompleted && !diagnosisLoading && (
        <dl className="diagnosis-results">
          <div><dt>Root cause</dt><dd>{formatRootCause(rootCause)}</dd></div>
          <div><dt>Recommended action</dt><dd><span className="action-badge">{formatAction(action)}</span></dd></div>
          <div><dt>Confidence</dt><dd>{confidence != null ? `${Math.round(confidence * 100)}%` : '-'}</dd></div>
          <div><dt>Explanation</dt><dd className="diagnosis-reason">{reason || 'No explanation provided.'}</dd></div>
          <div><dt>Risk factors</dt><dd><RiskFactorsList factorsJson={diagFactorsJson} /></dd></div>
        </dl>
      )}

      {isPending && !diagnosisLoading && !diagnosisError && (
        <div className="diagnosis-status-card diagnosis-pending">
          <span>Diagnosis not yet run. Click &quot;Run AI Diagnosis&quot; to analyze this case.</span>
        </div>
      )}
    </>
  );
}

function PolicyCheckSection({
  riskCase,
  policyResult,
  policyLoading,
  policyError,
  onRunPolicyCheck,
}: {
  riskCase: RecoveryCase | null;
  policyResult: PolicyResult | null;
  policyLoading: boolean;
  policyError: string | null;
  onRunPolicyCheck: () => void;
}) {
  if (!riskCase) return null;

  const hasDiagnosis = riskCase.diagnosis_status === 'completed';
  const hasPolicy = policyResult !== null;
  const isAllowed = policyResult?.decision === 'ALLOW';
  const isBlocked = policyResult?.decision === 'BLOCK';

  return (
    <>
      <div className="detail-divider" />
      <div className="ai-diagnosis-header">
        <p className="eyebrow"><ShieldCheck size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />Policy Check</p>
        {hasDiagnosis && !hasPolicy && !policyLoading && (
          <button className="diagnose-btn" onClick={onRunPolicyCheck} disabled={policyLoading}>
            Run Policy Check
          </button>
        )}
      </div>

      {policyLoading && (
        <div className="diagnosis-status-card">
          <Loader2 size={18} className="spin" />
          <span>Running policy check...</span>
        </div>
      )}

      {policyError && (
        <div className="diagnosis-status-card diagnosis-error">
          <span>{policyError}</span>
        </div>
      )}

      {!hasDiagnosis && !policyLoading && (
        <div className="diagnosis-status-card diagnosis-pending">
          <span>Run AI Diagnosis first before policy check.</span>
        </div>
      )}

      {hasPolicy && !policyLoading && (
        <dl className="diagnosis-results">
          <div><dt>Requested action</dt><dd><span className="action-badge">{formatAction(policyResult.action)}</span></dd></div>
          <div><dt>Policy decision</dt>
            <dd>
              <span className={`policy-decision ${isAllowed ? 'policy-allow' : 'policy-block'}`}>
                {policyResult.decision}
              </span>
            </dd>
          </div>
          <div><dt>Reason</dt><dd className="diagnosis-reason">{policyResult.reason}</dd></div>
          <div>
            <dt>Rules evaluated</dt>
            <dd>
              <ul className="rules-list">
                {policyResult.rules_evaluated.map((rule, i) => (
                  <li key={i} className={rule.passed ? 'rule-passed' : 'rule-failed'}>
                    <span className="rule-icon">{rule.passed ? '\u2713' : '\u2717'}</span>
                    <span className="rule-name">{rule.rule}</span>
                    <span className="rule-detail">{rule.detail}</span>
                  </li>
                ))}
              </ul>
            </dd>
          </div>
          <div><dt>Policy version</dt><dd>{policyResult.policy_version}</dd></div>
          {isBlocked && (
            <div className="policy-blocked-notice">
              Action blocked by deterministic policy. The AI recommendation is not an approved action.
            </div>
          )}
        </dl>
      )}

      {hasDiagnosis && !hasPolicy && !policyLoading && !policyError && (
        <div className="diagnosis-status-card diagnosis-pending">
          <span>Policy not yet evaluated. Click &quot;Run Policy Check&quot; to validate the AI recommendation.</span>
        </div>
      )}
    </>
  );
}

function ExecutionSection({
  riskCase,
  policyResult,
  executionResult,
  executionLoading,
  executionError,
  executionHistory,
  onExecute,
}: {
  riskCase: RecoveryCase | null;
  policyResult: PolicyResult | null;
  executionResult: ExecutionResult | null;
  executionLoading: boolean;
  executionError: string | null;
  executionHistory: ExecutionHistoryItem[];
  onExecute: () => void;
}) {
  if (!riskCase) return null;

  const hasPolicy = policyResult !== null;
  const isAllowed = policyResult?.decision === 'ALLOW';
  const isBlocked = policyResult?.decision === 'BLOCK';
  const action = policyResult?.action;
  const isSupported = action === 'SEND_PAYMENT_LINK';
  const hasExecution = executionResult !== null;
  const isLinkCreated = executionResult?.execution_status === 'LINK_CREATED';

  return (
    <>
      <div className="detail-divider" />
      <div className="ai-diagnosis-header">
        <p className="eyebrow"><Zap size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />Recovery Execution</p>
        {hasPolicy && isAllowed && isSupported && !hasExecution && !executionLoading && (
          <button className="diagnose-btn execute-btn" onClick={onExecute} disabled={executionLoading}>
            Execute Recovery
          </button>
        )}
      </div>

      {executionLoading && (
        <div className="diagnosis-status-card">
          <Loader2 size={18} className="spin" />
          <span>Executing recovery action...</span>
        </div>
      )}

      {executionError && (
        <div className="diagnosis-status-card diagnosis-error">
          <span>{executionError}</span>
        </div>
      )}

      {isBlocked && hasPolicy && (
        <div className="diagnosis-status-card diagnosis-blocked">
          <span>Recovery blocked by policy. The AI recommendation was not approved for execution.</span>
        </div>
      )}

      {!hasPolicy && !executionLoading && (
        <div className="diagnosis-status-card diagnosis-pending">
          <span>Run Policy Check first to determine if execution is permitted.</span>
        </div>
      )}

      {hasPolicy && isAllowed && !isSupported && !executionLoading && (
        <div className="diagnosis-status-card diagnosis-pending">
          <span>Action &quot;{formatAction(action)}&quot; is not yet supported for execution.</span>
        </div>
      )}

      {hasExecution && !executionLoading && (
        <dl className="diagnosis-results">
          <div><dt>Execution status</dt>
            <dd>
              <span className={`execution-status exec-${executionResult.execution_status.toLowerCase()}`}>
                {executionResult.execution_status.replace(/_/g, ' ')}
              </span>
            </dd>
          </div>
          <div><dt>Policy decision</dt><dd>{executionResult.policy_decision}</dd></div>
          {executionResult.razorpay_reference && (
            <div><dt>Razorpay reference</dt><dd className="monospace">{executionResult.razorpay_reference}</dd></div>
          )}
          {executionResult.payment_link_url && (
            <div><dt>Payment link</dt><dd><a href={executionResult.payment_link_url} target="_blank" rel="noopener noreferrer" className="payment-link">{executionResult.payment_link_url}</a></dd></div>
          )}
          <div><dt>Message</dt><dd className="diagnosis-reason">{executionResult.message}</dd></div>
          <div><dt>Timestamp</dt><dd>{formatDate(executionResult.created_at)}</dd></div>
          {isLinkCreated && (
            <div className="policy-blocked-notice" style={{ background: '#e7f7ee', color: '#087443' }}>
              Payment link created. Awaiting customer payment. Money has NOT been recovered yet.
            </div>
          )}
        </dl>
      )}

      {executionHistory.length > 0 && (
        <>
          <div className="detail-divider" />
          <div>
            <p className="eyebrow">Execution History</p>
          </div>
          <div className="execution-history">
            {executionHistory.map((item) => (
              <div key={item.id} className="execution-history-item">
                <span className={`execution-status exec-${item.execution_status.toLowerCase()}`}>
                  {item.execution_status.replace(/_/g, ' ')}
                </span>
                <span className="execution-action">{formatAction(item.action)}</span>
                <span className="execution-time">{formatDate(item.created_at)}</span>
                {item.razorpay_reference && <span className="execution-ref monospace">{item.razorpay_reference}</span>}
                {item.error_message && <span className="execution-error">{item.error_message}</span>}
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}

function OutcomeSection({
  riskCase,
  executionHistory,
}: {
  riskCase: RecoveryCase | null;
  executionHistory: ExecutionHistoryItem[];
}) {
  if (!riskCase) return null;
  // Derive outcome from execution history (most recent action)
  const latest = executionHistory[0] || null;
  const outcomeStatus = latest?.execution_status || null;
  const amountRecovered = riskCase.amount_recovered;
  const hasAmount = Number(amountRecovered) > 0;
  const isSuccess = outcomeStatus === 'PAYMENT_SUCCESS';
  const isFailed = outcomeStatus === 'PAYMENT_FAILED';
  const isBlocked = outcomeStatus === 'BLOCKED';
  const isPending = outcomeStatus === 'LINK_CREATED' || outcomeStatus === 'PAYMENT_PENDING';

  return (
    <>
      <div className="detail-divider" />
      <div>
        <p className="eyebrow">Outcome</p>
      </div>
      {!latest && (
        <div className="diagnosis-status-card diagnosis-pending">
          <span>No outcome yet. Outcome is recorded only after a verified Razorpay payment event.</span>
        </div>
      )}
      {latest && (
        <dl className="diagnosis-results">
          <div><dt>AI Recommendation</dt><dd><span className="action-badge">{formatAction(riskCase.recommended_action || latest.action)}</span></dd></div>
          <div><dt>Policy</dt><dd>{isBlocked ? <span className="policy-decision policy-block">BLOCK</span> : <span className="policy-decision policy-allow">ALLOW</span>}</dd></div>
          <div><dt>Execution</dt><dd><span className={`execution-status exec-${outcomeStatus?.toLowerCase()}`}>{outcomeStatus?.replace(/_/g, ' ')}</span></dd></div>
          <div><dt>Outcome</dt><dd>
            {isSuccess && <span className="execution-status exec-payment_success">PAYMENT SUCCESS</span>}
            {isFailed && <span className="execution-status exec-payment_failed">PAYMENT FAILED</span>}
            {isPending && <span className="execution-status exec-payment_pending">PAYMENT PENDING — Link created, awaiting payment</span>}
            {isBlocked && <span className="execution-status exec-blocked">BLOCKED — No payment link created</span>}
            {!isSuccess && !isFailed && !isPending && !isBlocked && <span>{outcomeStatus}</span>}
          </dd></div>
          <div><dt>Amount Recovered</dt><dd>{money(amountRecovered, riskCase.currency || 'INR')} {hasAmount ? '' : '(still 0 — only verified payment success increases this)'}</dd></div>
          {isSuccess && (
            <div className="policy-blocked-notice" style={{ background: '#e7f7ee', color: '#087443' }}>
              Revenue recovered via verified Razorpay payment. This is actual recovered amount from the webhook event.
            </div>
          )}
          {isFailed && (
            <div className="policy-blocked-notice">
              Payment failed. Amount recovered remains zero per non-double-counting rule.
            </div>
          )}
          {isPending && (
            <div className="diagnosis-status-card diagnosis-pending">
              <span>Payment link created — not yet paid. amount_recovered = 0 until payment.captured webhook verifies success.</span>
            </div>
          )}
        </dl>
      )}
      <div style={{ marginTop: 8, fontSize: '.76rem', color: 'var(--muted-text)' }}>
        Chain: AI Diagnosis → Policy Decision → Execution → Outcome. Only verified payment success may increase amount_recovered.
      </div>
    </>
  );
}

function EvaluationSection({
  evaluation,
  evalLoading,
  evalError,
  onRun,
}: {
  evaluation: import('@/services/recoverai-api').EvaluationResult | null;
  evalLoading: boolean;
  evalError: string | null;
  onRun: () => void;
}) {
  return (
    <section className="panel" style={{ margin: '18px 0' }}>
      <div className="ai-diagnosis-header">
        <div>
          <p className="eyebrow">Simulated Batch Evaluation</p>
          <h2>Recovery Performance — Deterministic Evaluation</h2>
          <p className="muted" style={{ fontSize: '.82rem', marginTop: 6 }}>Clearly labeled SIMULATED. Does NOT create live Razorpay payment links. Metrics calculated from actual stored transaction/outcome data. Simulated execution mirrors: Risk → Diagnosis → Policy → Simulated outcome.</p>
        </div>
        <button className="diagnose-btn execute-btn" onClick={onRun} disabled={evalLoading}>
          {evalLoading ? <><Loader2 size={14} className="spin" /> Running...</> : 'Run Batch Evaluation'}
        </button>
      </div>

      {evalLoading && (
        <div className="diagnosis-status-card" style={{ marginTop: 12 }}><Loader2 size={18} className="spin" /><span>Running deterministic simulation over 520 synthetic transactions...</span></div>
      )}
      {evalError && (
        <div className="diagnosis-status-card diagnosis-error" style={{ marginTop: 12 }}><span>{evalError}</span></div>
      )}

      {evaluation && evaluation.evaluation_type !== 'NONE' && !evalLoading && (
        <>
          <div className="kpi-grid" style={{ marginTop: 16 }}>
            <div className="kpi-card risk"><p>Revenue at Risk</p><strong>{money(evaluation.revenue_at_risk)}</strong><span>{evaluation.recovery_cases ?? evaluation.dataset_size} recovery cases • {evaluation.eligible_cases ?? '-'} eligible</span></div>
            <div className="kpi-card"><p>Revenue Recovered (Simulated)</p><strong>{money(evaluation.amount_recovered)}</strong><span>Successful: {evaluation.successful_recoveries} • Failed: {evaluation.failed_recoveries ?? '-'}</span></div>
            <div className="kpi-card review"><p>Recovery Rate</p><strong>{(evaluation.recovery_rate * 100).toFixed(2)}%</strong><span>amount_recovered / revenue_at_risk</span></div>
            <div className="kpi-card"><p>Case Recovery Rate</p><strong>{(evaluation.case_recovery_rate * 100).toFixed(1)}%</strong><span>successful / eligible</span></div>
          </div>
          <div className="kpi-grid" style={{ marginTop: 12 }}>
            <div className="kpi-card"><p>Cases Processed</p><strong>{evaluation.dataset_size}</strong><span>Total synthetic transactions</span></div>
            <div className="kpi-card"><p>Successful Recoveries</p><strong>{evaluation.successful_recoveries}</strong><span>Simulated PAYMENT_SUCCESS</span></div>
            <div className="kpi-card"><p>Policy Allowed</p><strong>{evaluation.policy_allowed}</strong><span>Blocked: {evaluation.policy_blocked}</span></div>
            <div className="kpi-card"><p>Recovery Attempts</p><strong>{evaluation.recovery_attempts}</strong><span>Simulated payment links</span></div>
          </div>
          <div style={{ marginTop: 12, padding: 12, borderRadius: 12, background: 'var(--muted)', fontSize: '.82rem', lineHeight: 1.6 }}>
            <div><strong>Baseline (simulated):</strong> No automated recovery — ₹0 recovered. <span className="muted">{evaluation.baseline_note || ''}</span></div>
            <div className="muted" style={{ marginTop: 4 }}>Formulas: recovery_rate = amount_recovered / revenue_at_risk (when revenue_at_risk &gt; 0); case_recovery_rate = successful_recoveries / eligible_cases.</div>
            <div className="muted" style={{ marginTop: 4 }}>Evaluation type: <strong>{evaluation.evaluation_type}</strong> • Updated: {evaluation.created_at ? formatDate(evaluation.created_at) : '-'}</div>
            <div className="muted" style={{ marginTop: 4, fontStyle: 'italic' }}>Test Mode payment results (real Razorpay Test API calls via Execution section) vs Simulated batch evaluation (above) are distinct — do not conflate simulated recovered revenue with real Razorpay revenue.</div>
          </div>
        </>
      )}
      {(!evaluation || evaluation.evaluation_type === 'NONE') && !evalLoading && !evalError && (
        <div className="diagnosis-status-card diagnosis-pending" style={{ marginTop: 12 }}><span>No evaluation yet. Click &quot;Run Batch Evaluation&quot; to run deterministic simulation over the 520-record synthetic dataset.</span></div>
      )}
    </section>
  );
}

function formatRootCause(rc: string | null | undefined): string {
  if (!rc) return '-';
  return rc.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function formatAction(action: string | null | undefined): string {
  if (!action) return '-';
  return action.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function TransactionDetail({
  transaction,
  riskCase,
  diagnosis,
  diagnosisLoading,
  diagnosisError,
  onRunDiagnosis,
  policyResult,
  policyLoading,
  policyError,
  onRunPolicyCheck,
  executionResult,
  executionLoading,
  executionError,
  executionHistory,
  onExecute,
}: {
  transaction: Transaction | null;
  riskCase: RecoveryCase | null;
  diagnosis: DiagnosisResult | null;
  diagnosisLoading: boolean;
  diagnosisError: string | null;
  onRunDiagnosis: () => void;
  policyResult: PolicyResult | null;
  policyLoading: boolean;
  policyError: string | null;
  onRunPolicyCheck: () => void;
  executionResult: ExecutionResult | null;
  executionLoading: boolean;
  executionError: string | null;
  executionHistory: ExecutionHistoryItem[];
  onExecute: () => void;
}) {
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
        <div><dt>Retry count</dt><dd>{transaction.retry_count}</dd></div>
        <div><dt>Prior successful payments</dt><dd>{transaction.previous_successful_payments}</dd></div>
        <div><dt>Customer lifetime value</dt><dd>{money(transaction.customer_lifetime_value)}</dd></div>
        <div><dt>Hours since event</dt><dd>{transaction.hours_since_event}h</dd></div>
        <div><dt>Revenue at risk</dt><dd>{transaction.is_revenue_at_risk ? 'Yes' : 'No'}</dd></div>
      </dl>

      {riskCase && (
        <>
          <div className="detail-divider" />
          <div>
            <p className="eyebrow">Deterministic Risk Assessment</p>
          </div>
          <dl>
            <div><dt>Risk score</dt><dd>{riskCase.risk_score} / 100</dd></div>
            <div><dt>Risk level</dt><dd><RiskLevelBadge level={riskCase.risk_level} /></dd></div>
            <div><dt>Recovery priority</dt><dd><PriorityBar value={riskCase.recovery_priority} /></dd></div>
            <div><dt>Risk factors</dt><dd><RiskFactorsList factorsJson={riskCase.risk_factors} /></dd></div>
          </dl>

          <DiagnosisSection
            riskCase={riskCase}
            diagnosis={diagnosis}
            diagnosisLoading={diagnosisLoading}
            diagnosisError={diagnosisError}
            onRunDiagnosis={onRunDiagnosis}
          />

          <PolicyCheckSection
            riskCase={riskCase}
            policyResult={policyResult}
            policyLoading={policyLoading}
            policyError={policyError}
            onRunPolicyCheck={onRunPolicyCheck}
          />

          <ExecutionSection
            riskCase={riskCase}
            policyResult={policyResult}
            executionResult={executionResult}
            executionLoading={executionLoading}
            executionError={executionError}
            executionHistory={executionHistory}
            onExecute={onExecute}
          />

          <OutcomeSection riskCase={riskCase} executionHistory={executionHistory} />
        </>
      )}
    </aside>
  );
}

export default function Home() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [riskSummary, setRiskSummary] = useState<RiskSummary | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [apiMode, setApiMode] = useState('checking');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<import('@/services/recoverai-api').EvaluationResult | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalError, setEvalError] = useState<string | null>(null);

  // Diagnosis state
  const [diagnosis, setDiagnosis] = useState<DiagnosisResult | null>(null);
  const [diagnosisLoading, setDiagnosisLoading] = useState(false);
  const [diagnosisError, setDiagnosisError] = useState<string | null>(null);

  // Policy state
  const [policyResult, setPolicyResult] = useState<PolicyResult | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);

  // Execution state
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [executionLoading, setExecutionLoading] = useState(false);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [executionHistory, setExecutionHistory] = useState<ExecutionHistoryItem[]>([]);

  useEffect(() => {
    Promise.all([
      recoverAiApi.getHealth(),
      recoverAiApi.getSummary(),
      recoverAiApi.getRecoveryCases(),
      recoverAiApi.getTransactions(),
      recoverAiApi.getRiskSummary(),
      recoverAiApi.getLatestEvaluation().catch(() => null),
    ])
      .then(([health, summaryData, caseData, transactionData, riskData, evalData]) => {
        setApiMode(health.mode);
        setSummary(summaryData);
        setCases(caseData);
        setTransactions(transactionData);
        setRiskSummary(riskData);
        if (evalData && evalData.evaluation_type !== 'NONE') setEvaluation(evalData as import('@/services/recoverai-api').EvaluationResult);
        setSelectedId(caseData[0]?.transaction_id || transactionData[0]?.id || null);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const selectedTransaction = useMemo(
    () => transactions.find((item) => item.id === selectedId) || null,
    [transactions, selectedId],
  );

  const selectedRiskCase = useMemo(
    () => cases.find((item) => item.transaction_id === selectedId) || null,
    [cases, selectedId],
  );

  // Load diagnosis when selecting a case
  useEffect(() => {
    if (!selectedRiskCase) {
      setDiagnosis(null);
      setDiagnosisError(null);
      setPolicyResult(null);
      setPolicyError(null);
      setExecutionResult(null);
      setExecutionError(null);
      setExecutionHistory([]);
      return;
    }
    if (selectedRiskCase.diagnosis_status === 'completed') {
      recoverAiApi.getDiagnosis(selectedRiskCase.id)
        .then(setDiagnosis)
        .catch(() => setDiagnosis(null));
    } else {
      setDiagnosis(null);
    }
    // Load existing policy decision
    recoverAiApi.getPolicyDecision(selectedRiskCase.id)
      .then(setPolicyResult)
      .catch(() => setPolicyResult(null));
    // Load execution history
    recoverAiApi.getExecutionHistory(selectedRiskCase.id)
      .then((data) => setExecutionHistory(data.actions || []))
      .catch(() => setExecutionHistory([]));
  }, [selectedRiskCase]);

  const handleRunDiagnosis = useCallback(async () => {
    if (!selectedRiskCase) return;
    setDiagnosisLoading(true);
    setDiagnosisError(null);
    try {
      const result = await recoverAiApi.runDiagnosis(selectedRiskCase.id);
      setDiagnosis(result);
      if (result.diagnosis_status === 'ai_unavailable') {
        setDiagnosisError(result.error || 'AI service unavailable');
      } else if (result.diagnosis_status === 'parse_error') {
        setDiagnosisError(result.error || 'Invalid AI response');
      } else if (result.diagnosis_status !== 'completed') {
        setDiagnosisError('Diagnosis did not complete successfully');
      }
      // Refresh cases list to pick up persisted diagnosis
      const updatedCases = await recoverAiApi.getRecoveryCases();
      setCases(updatedCases);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Diagnosis failed';
      setDiagnosisError(msg);
    } finally {
      setDiagnosisLoading(false);
    }
  }, [selectedRiskCase]);

  const handleRunPolicyCheck = useCallback(async () => {
    if (!selectedRiskCase) return;
    setPolicyLoading(true);
    setPolicyError(null);
    try {
      const result = await recoverAiApi.runPolicyCheck(selectedRiskCase.id);
      setPolicyResult(result);
      if (result.decision === 'error') {
        setPolicyError('Policy check failed');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Policy check failed';
      setPolicyError(msg);
    } finally {
      setPolicyLoading(false);
    }
  }, [selectedRiskCase]);

  const handleExecute = useCallback(async () => {
    if (!selectedRiskCase || !policyResult) return;
    setExecutionLoading(true);
    setExecutionError(null);
    try {
      const result = await recoverAiApi.executeRecoveryAction(selectedRiskCase.id, policyResult.action);
      setExecutionResult(result);
      if (result.execution_status === 'EXECUTION_FAILED') {
        setExecutionError(result.message);
      }
      // Refresh execution history
      const history = await recoverAiApi.getExecutionHistory(selectedRiskCase.id);
      setExecutionHistory(history.actions || []);
      // Refresh cases to pick up amount_recovered after outcome updates (webhook may update it later)
      const updatedCases = await recoverAiApi.getRecoveryCases();
      setCases(updatedCases);
      const summaryData = await recoverAiApi.getSummary();
      setSummary(summaryData);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Execution failed';
      setExecutionError(msg);
    } finally {
      setExecutionLoading(false);
    }
  }, [selectedRiskCase, policyResult]);

  const handleRunEvaluation = useCallback(async () => {
    setEvalLoading(true);
    setEvalError(null);
    try {
      const result = await recoverAiApi.runEvaluation();
      setEvaluation(result);
      // Refresh summary to reflect any real webhook amount_recovered vs simulated separate
      const summaryData = await recoverAiApi.getSummary();
      setSummary(summaryData);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Evaluation failed';
      setEvalError(msg);
    } finally {
      setEvalLoading(false);
    }
  }, []);

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
        <KpiCard tone="risk" label="High Risk Revenue" value={riskSummary ? money(riskSummary.high_risk_revenue) : '-'} helper={riskSummary ? `${riskSummary.high_risk_cases} high-risk cases` : 'Loading...'} />
        <KpiCard label="Revenue Recovered (Verified)" value={money(summary.revenue_recovered)} helper="Only verified Razorpay payments" />
        <KpiCard label="Recovery Rate" value={`${summary.recovery_rate}%`} helper="recovered / at-risk (verified only)" />
      </section>

      <EvaluationSection evaluation={evaluation} evalLoading={evalLoading} evalError={evalError} onRun={handleRunEvaluation} />

      <section className="kpi-grid" aria-label="Risk distribution">
        <KpiCard tone="risk" label="High Risk Cases" value={riskSummary?.high_risk_cases ?? '-'} helper="Score 80-100" />
        <KpiCard tone="review" label="Medium Risk Cases" value={riskSummary?.medium_risk_cases ?? '-'} helper="Score 50-79" />
        <KpiCard label="Low Risk Cases" value={riskSummary?.low_risk_cases ?? '-'} helper="Score 0-49" />
        <KpiCard label="Total Risk Cases" value={riskSummary?.total_risk_cases ?? '-'} helper={`${summary.total_transactions} total transactions`} />
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
          <div className="section-heading"><ShieldCheck size={20} /><h2>Architecture Boundaries</h2></div>
          <ul>
            <li>Risk scoring is deterministic and explainable (no LLM).</li>
            <li>AI diagnosis provides root-cause analysis and recommendations.</li>
            <li>Policy engine validates actions before execution.</li>
            <li>Razorpay Test Mode creates payment links after policy approval.</li>
            <li>Webhooks verify payment success before marking revenue recovered.</li>
            <li>Simulated batch evaluation measures performance without live Razorpay calls.</li>
          </ul>
        </article>
      </section>

      <section className="workspace-grid">
        <article className="panel table-panel">
          <div className="section-heading"><FileSearch size={20} /><h2>Recovery Cases</h2></div>
          {cases.length === 0 ? <div className="empty-row">No failed or abandoned transactions need review.</div> : (
            <div className="table-wrap">
              <table>
                <thead><tr>
                  <th>Case / Transaction</th><th>Customer</th><th>Amount</th><th>Status</th>
                  <th>Risk</th><th>Level</th><th>Priority</th>
                  <th>Failure Reason</th><th>Created At</th>
                </tr></thead>
                <tbody>
                  {cases.map((item) => (
                    <tr key={item.id} onClick={() => setSelectedId(item.transaction_id)} className={selectedId === item.transaction_id ? 'selected' : ''}>
                      <td><strong>{item.id}</strong><span>{item.transaction_id}</span></td>
                      <td>{item.customer_name}</td>
                      <td>{money(item.amount, item.currency || 'INR')}</td>
                      <td><StatusBadge status={item.transaction_status} /></td>
                      <td><RiskBar value={item.risk_score} /></td>
                      <td><RiskLevelBadge level={item.risk_level} /></td>
                      <td><PriorityBar value={item.recovery_priority} /></td>
                      <td>{item.failure_reason || 'Not provided'}</td>
                      <td>{formatDate(item.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
        <TransactionDetail
          transaction={selectedTransaction}
          riskCase={selectedRiskCase}
          diagnosis={diagnosis}
          diagnosisLoading={diagnosisLoading}
          diagnosisError={diagnosisError}
          onRunDiagnosis={handleRunDiagnosis}
          policyResult={policyResult}
          policyLoading={policyLoading}
          policyError={policyError}
          onRunPolicyCheck={handleRunPolicyCheck}
          executionResult={executionResult}
          executionLoading={executionLoading}
          executionError={executionError}
          executionHistory={executionHistory}
          onExecute={handleExecute}
        />
      </section>

      <footer className="demo-note"><AlertTriangle size={16} /> This preview uses deterministic synthetic demo data through the FastAPI backend. Risk scores are computed by a deterministic rule engine. AI diagnosis uses a local LLM (Ollama). Razorpay integration uses Test Mode only.</footer>
    </main>
  );
}
