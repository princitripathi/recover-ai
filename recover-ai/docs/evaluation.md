# Evaluation — Simulated Batch Evaluation

> RecoverAI measures recovery performance using deterministic simulation over the synthetic dataset.
> No live Razorpay API calls are made during batch evaluation. All numbers are calculated from
> stored transactions, diagnosed cases, and simulated outcomes. The evaluation is **always labeled
> SIMULATED** and must not be presented as real recovered revenue.

## 1. Dataset

- Source: `recover-ai/data/demo_transactions.csv` — 520 synthetic transactions with `generate_data.py`.
- Transaction statuses: `paid`, `failed`, `abandoned`, `pending`. Recovery cases are created for
  every `failed` or `abandoned` transaction (typically ~185–195 cases per fresh DB).
- Attributes per transaction: `amount`, `currency`, `payment_method`, `failure_reason`, `retry_count`,
  `previous_successful_payments`, `customer_lifetime_value`, `hours_since_event`, `checkout_session_id`,
  `created_at`.
- Risk assessment: deterministic `risk_service.assess_transaction` scores every case (0–100) into
  HIGH/MEDIUM/LOW with recovery `priority` (0–1).

Total revenue and revenue at risk are **direct SQL aggregates** over the database:

```sql
SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM transactions
SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM transactions WHERE status IN ('failed','abandoned')
```

## 2. Evaluation Methodology

The evaluation runs the same business pipeline as the interactive path, but with two
simulation layers to avoid LLM and Razorpay costs:

```
For each recovery case (JOIN transaction + risk row, ordered by case_id):
  1) Diagnosis simulation (no LLM): deterministic mapping failure_reason → root_cause + recommended_action
     - TEMPORARY failures → SEND_PAYMENT_LINK or RETRY_PAYMENT, confidence 0.85
     - Insufficient funds → SEND_PAYMENT_LINK, 0.72
     - Bank/system decline → CONTACT_CUSTOMER, 0.65
     - Abandoned / no reason → CUSTOMER_ABANDONMENT / SEND_PAYMENT_LINK, 0.78
     - Unknown/permanent → variants of NO_ACTION/ESCALATE/CONTACT_CUSTOMER (see services/evaluation_service.py)
  2) Policy simulation (no DB write): re-applies the deterministic policy rules from policy_service
     — amount limits, HIGH-risk gating, retry count, confidence threshold — returns ALLOW/BLOCK.
  3) Simulated execution: only ALLOW + SEND_PAYMENT_LINK/RETRY_PAYMENT count as recovery_attempts.
     Outcome (PAYMENT_SUCCESS vs PAYMENT_FAILED) is a stable hash of case_id (+ priority adjustment):
       roll = SHA256(case_id) % 100; threshold bumps with priority (55/65/72);
       roll < threshold → SUCCESS else FAILED.
     This threshold yields ~60–65% success for simulated attempts — deterministic and repeatable.
  4) Amount recovered accumulates the original transaction amount (as verified-amount proxy) for
     each simulated PAYMENT_SUCCESS.
```

Implementation: `recover-ai/backend/app/services/evaluation_service.py` (`run_evaluation`, helpers).

No database rows for `amount_recovered` or `status` are mutated by evaluation — it persists
only to `evaluation_runs`. Real webhook-verified recoveries still flow exclusively through
`webhooks` → `recovery_actions` → `recovery_cases.amount_recovered`.

Determinism: every run over identical data produces bit-identical metrics. Tests assert
`run → run` repeatability.

## 3. Metrics

All metrics are calculated **after** the simulated loop; none are invented.

| Metric | Source |
|--------|--------|
| `total_transactions` | COUNT(transactions) |
| `total_revenue` | SUM(amount) over all transactions |
| `revenue_at_risk` | SUM(amount) WHERE status IN ('failed','abandoned') |
| `recovery_cases` | COUNT(recovery_cases) |
| `eligible_cases` | = recovery_cases |
| `policy_allowed` | ALLOW count from simulated policy |
| `policy_blocked` | BLOCK count |
| `recovery_attempts` | ALLOW ∧ action ∈ {SEND_PAYMENT_LINK, RETRY_PAYMENT} |
| `successful_recoveries` | Simulated PAYMENT_SUCCESS count |
| `failed_recoveries` | Simulated PAYMENT_FAILED count |
| `amount_recovered` | Σ(amount) for PAYMENT_SUCCESS |
| `recovery_rate` | amount_recovered / revenue_at_risk  (0 if denominator 0) |
| `case_recovery_rate` | successful_recoveries / eligible_cases |
| `baseline_recovered` | 0.00 — “No automated recovery (simulated baseline)” |
| `dataset_size` | = total_transactions (520) |

## 4. Metric Formulas

```
recovery_rate =
  amount_recovered / revenue_at_risk   if revenue_at_risk > 0
  0                                    otherwise

case_recovery_rate =
  successful_recoveries / eligible_cases   if eligible_cases > 0
  0                                        otherwise
```

Amounts are `Decimal("0.00")` quantized; `recovery_rate` is a fraction 0–1 (display ×100%).
`recovery_rate` is **not** a fabricated percentage — both numerator and denominator
come from the DB or deterministic simulation.

## 5. Simulated vs Real Razorpay Execution

| Path | What Happens | When |
|------|--------------|------|
| Interactive execution (Test Mode) | `POST /api/recovery-cases/{id}/execute` checks policy ALLOW then calls live Razorpay API (`httpx`); on `payment.captured`/`payment.failed` webhook the service verifies HMAC and updates `recovery_actions`/`recovery_cases.amount_recovered`. | Per-case, user-initiated. Results show under “Revenue Recovered (Verified)”. |
| Simulated batch evaluation | No httpx calls. Diagnosis/policy/outcome are in-process deterministic simulations over the full 520 records. Amount uses transaction amount as verified-amount proxy. | `POST /api/evaluation/run`, persisted to `evaluation_runs`. Dashboard shows under “Simulated Batch Evaluation” with explicit SIMULATED label. |

Never conflate the two. The dashboard distinguishes them textually:
- Test Mode payment results (real Razorpay Test API, still $0 real money) vs
- Simulated batch evaluation (no network, no Razorpay, synthetic math).

## 6. Webhook Verification

Official Razorpay verification: `HMAC-SHA256(raw_body, RAZORPAY_WEBHOOK_SECRET)` hex digest
compared with `X-Razorpay-Signature`. Implementation: `services/webhook_service.verify_signature`.

- Missing `X-Razorpay-Signature` → 400 `{error: "missing_signature"}`.
- Mismatch → 400 `{error: "invalid_signature"}`.
- If no `RAZORPAY_WEBHOOK_SECRET` is configured → request rejected (do not trust unverified).
- Secrets never appear in API responses. Passed to compare via constant-time `hmac.compare_digest`.
- Forwarded through the Next.js API route `/api/[...path]` which preserves the raw body bytes for
  verification (headers include `x-razorpay-signature`).

Configuration (`recover-ai/.env.example`):

```
RECOVERAI_RAZORPAY_WEBHOOK_SECRET=whsec_...   # or RAZORPAY_WEBHOOK_SECRET with RECOVERAI_ prefix
```

## 7. Idempotency

- `webhook_events.event_id` is `UNIQUE`. First delivery INSERTs `received`; second identical
  `event_id` is detected before reprocessing and returns `{status: "duplicate"}` with HTTP 200.
- Success transitions are guarded: if `recovery_actions.execution_status` already `PAYMENT_SUCCESS`,
  a repeated `payment.captured` for the same action returns `duplicate` and does not re-add
  `amount_recovered`.
- Duplicate `PAYMENT_SUCCESS` leaves `amount_recovered` unchanged — verified by tests
  “amount_recovered changes only once” and “duplicate payment.captured does not double-count revenue”.

## 8. Limitations

- Evaluation diagnosis is rule-based, not LLM-based, to keep it fast and deterministic. Real
  `diagnose` calls still go through Ollama for interactive cases.
- Simulated outcome threshold is heuristic (~60% success); real Razorpay capture rates may differ.
- The simulated “verified amount” proxy uses the transaction amount; real webhooks use the Razorpay
  `payment.entity.amount` (paise) as the source of truth — the webhook path is the only one that
  updates operational revenue.
- No RETRY_PAYMENT execution beyond simulation; `retry_payment` in evaluation is counted as an
  attempt but not wired to Razorpay Orders API.
- Authentication/merchant tenancy is not implemented.

## 9. Example Results (generated by the actual evaluation)

Fresh DB (`520` synthetic transactions, `backend/.venv` with `pytest -q` fixture):

```json
{
  "evaluation_type": "SIMULATED",
  "dataset_size": 520,
  "total_revenue": "4429765.10",
  "revenue_at_risk": "1371221.08",
  "recovery_cases": 191,
  "eligible_cases": 191,
  "policy_allowed": 188,
  "policy_blocked": 3,
  "recovery_attempts": 95,
  "successful_recoveries": 55,
  "failed_recoveries": 40,
  "amount_recovered": "422956.32",
  "recovery_rate": 0.3085,
  "case_recovery_rate": 0.288,
  "baseline_recovered": "0.00",
  "baseline_note": "No automated recovery (simulated baseline) — 0 recovered",
  "created_at": "2026-09-05T21:29:44+05:30"
}
```

Interpretation: with simulated policy and ~60% link-conversion heuristic,
RecoverAI would recover ₹422,956.32 of ₹1,371,221.08 at risk (30.85% revenue recovery rate,
28.8% of cases) while the baseline (no automated recovery) remains 0. Simulated — not real money.

Persisted via `POST /api/evaluation/run`; retrieved via `GET /api/evaluation/latest`.
Dashboard renders the latest run verbatim alongside verified revenue for comparison.
