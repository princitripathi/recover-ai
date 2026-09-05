# RecoverAI

RecoverAI is an AI-powered Revenue Recovery platform foundation for merchants. It identifies deterministic revenue at risk from payment events, presents recovery cases for review, and keeps clean module boundaries for future AI diagnosis, policy enforcement, Razorpay Test Mode, recovery execution, and outcome tracking.

This version is a synthetic demo environment only. It does not use real merchant data, does not handle real money, and does not include authentication. Razorpay integration uses Test Mode only; simulated batch evaluation does NOT create live payment links.

## Implemented Functionality

### Stage 1 — Foundation
- Next.js React frontend used by the Ideavo preview
- FastAPI REST API with SQLite persistence
- Synthetic transaction seeding from `data/demo_transactions.csv`
- Transaction and recovery-case data models
- Deterministic revenue-at-risk calculation: failed + abandoned transaction amounts
- Dashboard summary metrics calculated from the database
- Responsive React merchant dashboard with KPI cards, recovery cases, and transaction detail view
- Backend tests for health, transaction retrieval, dashboard summary, and revenue-at-risk calculation

### Stage 2 — Revenue Risk Detection
- Expanded synthetic dataset: 520 realistic transactions with varied attributes
- Deterministic risk scoring engine (0-100, no LLM)
- Risk levels: HIGH (80-100), MEDIUM (50-79), LOW (0-49)
- Structured risk factors explaining every score
- Recovery priority calculation combining revenue impact and recovery likelihood
- Risk API: filterable, sortable case listing with summary
- Risk dashboard: HIGH/MEDIUM/LOW counts, revenue breakdown, risk distribution
- Case detail view with transaction attributes and deterministic risk assessment
- 47 backend tests including comprehensive risk engine tests

### Stage 3 — AI Diagnosis
- AI diagnosis service using local LLM (Ollama, qwen2.5:3b)
- Structured output: root cause, recommended action, confidence, explanation
- Controlled vocabulary for root causes and recovery actions
- Pydantic validation of LLM responses
- Graceful degradation when LLM is unavailable (AI_UNAVAILABLE status)
- Diagnosis persistence to database
- Frontend diagnosis UI with Run button, loading/error/unavailable states
- 30 additional diagnosis tests (77 total backend tests)

### Stage 4 — Deterministic Policy Engine
- Deterministic policy engine (no LLM, fully rule-based)
- Independently authorizes or blocks AI-recommended recovery actions
- Configurable policy thresholds via environment variables
- Policy rules for all 5 controlled actions (RETRY_PAYMENT, SEND_PAYMENT_LINK, CONTACT_CUSTOMER, ESCALATE, NO_ACTION)
- AI confidence threshold enforcement
- Amount limit enforcement
- Risk level gating (HIGH risk blocks automated actions)
- Policy decision persistence with audit trail
- Frontend policy check UI with Run button, decision display, rules evaluated
- Policy engine never calls LLM or Razorpay
- 30 additional policy tests (107 total backend tests)

### Stage 5 — Razorpay Test Mode Integration
- Razorpay Test Mode payment link creation via REST API (httpx, no SDK dependency)
- Execution service orchestrates: policy gate → Razorpay call → persist result
- Policy engine is the mandatory gatekeeper — BLOCK decisions never reach Razorpay
- Duplicate execution protection (idempotency via case_id + action)
- Full audit trail in `recovery_actions` table
- Payment link lifecycle tracking: LINK_CREATED → PAYMENT_PENDING → PAYMENT_SUCCESS/FAILED
- Money is NOT marked as recovered until actual payment success is verified
- Credentials loaded from environment variables (never hardcoded, never in API responses)
- Graceful error handling: missing credentials, API failures, timeouts, invalid data
- Frontend execution UI with Execute button, status display, payment link, execution history
- 25 additional execution tests (132 total backend tests)

### Stage 6 — Outcome Tracking, Webhooks and Measured Recovery
- Deterministic outcome state machine: LINK_CREATED → PAYMENT_PENDING → PAYMENT_SUCCESS/FAILED; BLOCKED, EXECUTION_FAILED variants
- Razorpay webhook endpoint POST /api/webhooks/razorpay with HMAC-SHA256 signature verification (official Razorpay mechanism)
- Webhook event storage (webhook_events table) with event_id uniqueness, processing_status, idempotent handling, duplicate detection
- Recovery outcome: payment.captured verifies payment, updates recovery action to PAYMENT_SUCCESS, transaction to paid, amount_recovered to actual Razorpay amount, audit log; payment.failed marks PAYMENT_FAILED without increasing revenue
- Validated Razorpay amount (paise) is used as source of truth, not original requested amount
- Amount double-count protection: repeated webhooks do not increase amount_recovered (idempotent outcome)
- Evaluation service: deterministic simulated batch evaluation over 520 synthetic transactions — does NOT call live Razorpay API
- Metrics: revenue_at_risk, amount_recovered, recovery_rate (amount_recovered/revenue_at_risk), case_recovery_rate, policy_allowed/blocked, recovery_attempts, etc., all calculated from stored data
- Control/baseline: simulated baseline “No automated recovery — 0 recovered” with explicit label
- Evaluation persistence: evaluation_runs table stores every run; GET /api/evaluation/latest and POST /api/evaluation/run
- Frontend: full chain AI Diagnosis → Policy Decision → Execution → Outcome with amount recovered, plus Evaluation / Recovery Performance section labeled SIMULATED BATCH EVALUATION; Run Batch Evaluation button with loading/error states
- Distinct labeling: Test Mode payment results vs Simulated batch evaluation
- Audit trail answers: at-risk reason, AI recommendation, policy allow/block with rules, Razorpay call, post-event outcome, amount recovered
- Docs: docs/evaluation.md with methodology, formulas, simulated vs real, webhook verification, idempotency, limitations, example results
- 37 additional webhook + evaluation tests (170 total backend tests)

## Tech Stack

- Frontend: React with Next.js App Router, TypeScript
- Backend: Python, FastAPI, Pydantic, httpx
- Database: SQLite with a simple service/database layer
- LLM: Ollama (qwen2.5:3b) for AI diagnosis
- Payments: Razorpay Test Mode REST API (via httpx)
- Tests: pytest and FastAPI TestClient

## Project Structure

```text
recover-ai/
  backend/
    app/
      main.py              # FastAPI app, CORS, lifespan
      config.py            # Pydantic Settings (LLM + Razorpay + webhook config)
      database.py          # SQLite schema, migrations, seeding
      models/              # Frozen dataclasses (Transaction, RecoveryCase)
      schemas/             # Pydantic models (transaction, recovery_case, dashboard, diagnosis, policy, execution)
      routes/              # REST endpoints (health, transactions, recovery_cases, dashboard, risk, diagnosis, policy, execution, webhooks, evaluation)
      services/            # Business logic (transaction, recovery, dashboard, risk, diagnosis, policy, razorpay, execution, webhook, evaluation)
    tests/
      test_api.py          # Stage 1 tests
      test_risk.py         # Stage 2 risk engine tests
      test_diagnosis.py    # Stage 3 AI diagnosis tests (mocked)
      test_policy.py       # Stage 4 policy engine tests
      test_execution.py    # Stage 5 execution tests (mocked Razorpay)
      test_webhook.py      # Stage 6 webhook + outcome tests (mocked, signature verified)
      test_evaluation.py   # Stage 6 evaluation + metrics tests
      conftest.py          # Test fixtures
    requirements.txt
  data/
    demo_transactions.csv  # 520 synthetic transactions
    generate_data.py       # Data generation script
  docs/architecture.md
  docs/evaluation.md
  README.md
  .env.example
  .gitignore
```

## Architecture

```
Transaction
  → Deterministic Risk Engine (score, level, factors)
    → AI Diagnosis (root cause, recommended action, confidence)
      → Policy Engine (deterministic: validates actions, ALLOW/BLOCK)
        → Razorpay Executor (creates payment links after policy approval) [Test Mode]
          → Webhook (X-Razorpay-Signature verified, idempotent)
            → Outcome State Machine (LINK_CREATED → PAYMENT_PENDING → PAYMENT_SUCCESS/FAILED)
              → Amount recovered (verified only) + Audit trail
        → Simulated Batch Evaluation (deterministic, no live Razorpay calls) → Metrics
```

## Risk Scoring Model

The deterministic risk engine calculates scores based on weighted transaction attributes:

| Factor | Weight | Range |
|--------|--------|-------|
| Transaction status | 0-35 | failed=33, abandoned=25, pending=10 |
| Transaction amount | 0-20 | Scaled by amount thresholds |
| Failure reason | 0-20 | Temporary failures score highest |
| Customer history | 0-16 | More prior payments = higher risk (more to recover) |
| Recency | 0-10 | Recent events score higher |

Risk levels: HIGH (80-100), MEDIUM (50-79), LOW (0-49)

Recovery priority (0.0-1.0) combines revenue impact, recovery likelihood, and customer lifetime value.

## AI Diagnosis

The AI diagnosis service calls a local LLM (Ollama) to analyze recovery cases and recommend recovery actions.

### Controlled Vocabulary

Root causes:
- `TEMPORARY_PAYMENT_FAILURE`
- `INSUFFICIENT_FUNDS`
- `BANK_DECLINE`
- `CUSTOMER_ABANDONMENT`
- `UNKNOWN_FAILURE`
- `HIGH_RISK_TRANSACTION`

Recovery actions:
- `RETRY_PAYMENT`
- `SEND_PAYMENT_LINK`
- `CONTACT_CUSTOMER`
- `ESCALATE`
- `NO_ACTION`

### Safety Design

- LLM receives only transaction and risk data — no secrets, no API keys
- LLM output is validated by Pydantic; invalid responses are rejected
- LLM never directly executes financial actions
- Policy engine validates actions before execution
- When LLM is unavailable, API returns `AI_UNAVAILABLE` status without crashing

## Policy Engine

The deterministic policy engine independently validates AI-recommended recovery actions before any financial operation is permitted.

### Policy Rules

| Action | Rules |
|--------|-------|
| RETRY_PAYMENT | Transaction must be failed, retry count < max, risk not HIGH, amount <= limit, confidence >= threshold, case eligible |
| SEND_PAYMENT_LINK | Transaction must be abandoned or failed, amount <= limit, risk not HIGH, case eligible |
| CONTACT_CUSTOMER | Transaction must be failed or abandoned, case eligible |
| ESCALATE | Always ALLOW |
| NO_ACTION | Always ALLOW |

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RECOVERAI_MAX_RETRY_AMOUNT` | 25000.0 | Maximum amount for retry payment |
| `RECOVERAI_MAX_PAYMENT_LINK_AMOUNT` | 50000.0 | Maximum amount for payment link |
| `RECOVERAI_MIN_AI_CONFIDENCE` | 0.6 | Minimum AI confidence for financial actions |
| `RECOVERAI_MAX_RETRY_COUNT` | 2 | Maximum retry attempts allowed |

### Safety Design

- Policy engine is completely deterministic — no LLM dependency
- AI recommendation never automatically becomes an executable action
- Policy decision is persisted with full audit trail
- Missing or unavailable diagnosis always results in BLOCK
- HIGH risk cases block all automated financial actions

## Razorpay Test Mode Integration

RecoverAI integrates with Razorpay Test Mode to create payment links after policy approval.

### Execution Flow

```
Recovery Case
  → AI Diagnosis (recommends SEND_PAYMENT_LINK)
    → Policy Check (ALLOW or BLOCK)
      → If ALLOW + credentials configured:
          → Razorpay REST API creates payment link
          → Payment link URL returned to frontend
          → Execution persisted to recovery_actions table
      → If BLOCK:
          → Razorpay is NEVER called
          → BLOCKED status returned with reason
```

### Payment Link Lifecycle

| Status | Meaning |
|--------|---------|
| LINK_CREATED | Razorpay payment link created successfully |
| PAYMENT_PENDING | Customer has not yet completed payment |
| PAYMENT_SUCCESS | Payment confirmed by Razorpay (webhook) |
| PAYMENT_FAILED | Payment attempt failed |
| EXECUTION_FAILED | Razorpay API error or credentials missing |
| BLOCKED | Policy engine denied execution |

### Idempotency

Duplicate execution protection uses `case_id + action` as a uniqueness constraint. If a successful execution already exists for a case+action combination, new execution attempts are blocked.

### Safety Design

- Policy engine is the mandatory gatekeeper — BLOCK decisions never reach Razorpay
- Credentials loaded from environment variables (never hardcoded, never in API responses)
- Payment link creation does NOT mark money as recovered
- Money is only considered recovered when payment success is verified via webhook
- Full audit trail in `recovery_actions` table for every execution attempt
- Only `SEND_PAYMENT_LINK` is implemented; other actions are future work

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RAZORPAY_KEY_ID` | (empty) | Razorpay Test Mode key ID |
| `RAZORPAY_KEY_SECRET` | (empty) | Razorpay Test Mode key secret |
| `RAZORPAY_BASE_URL` | `https://api.razorpay.com/v1` | Razorpay API base URL |
| `RAZORPAY_WEBHOOK_SECRET` | (empty) | Razorpay webhook secret for HMAC signature verification |

### Webhook Verification

Razorpay webhook signature uses HMAC-SHA256 of the raw request body with `RAZORPAY_WEBHOOK_SECRET`. The backend verifies `X-Razorpay-Signature` on every POST to /api/webhooks/razorpay and rejects invalid or missing signatures (400). Secrets are never exposed in API responses. Webhook events are stored idempotently via unique `event_id`.

### Outcome State Machine

Supported states: LINK_CREATED, PAYMENT_PENDING, PAYMENT_SUCCESS, PAYMENT_FAILED, EXECUTION_FAILED, BLOCKED. Only a verified Razorpay webhook (payment.captured / payment.failed) may transition LINK_CREATED/PAYMENT_PENDING → PAYMENT_SUCCESS/PAYMENT_FAILED. Direct transitions to PAYMENT_SUCCESS are forbidden. `amount_recovered` is set to the Razorpay-verified amount (paise → rupee) only on PAYMENT_SUCCESS and is never double-counted.

### Evaluation (Simulated)

POST /api/evaluation/run deterministically simulates the full logic (Risk → Diagnosis (rule-based) → Policy → Simulated outcome via stable hash) over the 520-record synthetic dataset without calling Razorpay. Metrics are persisted to `evaluation_runs` and retrieved via GET /api/evaluation/latest. Recovery rate = amount_recovered / revenue_at_risk; case_recovery_rate = successful_recoveries / eligible_cases. Baseline is “No automated recovery — 0 recovered” (simulated). Always labeled SIMULATED. See docs/evaluation.md.

### Audit Trail

Every recovery action is recorded in `recovery_actions` (plus `policy_decisions`, `webhook_events`, `audit_logs`). The trail answers: why at-risk (risk factors), AI recommendation, policy allow/block with rules, Razorpay call, post-event outcome, amount recovered. Historical decisions are never overwritten.

## Run Backend

```bash
cd recover-ai/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Run Frontend Preview

The active frontend application is the repository root Next.js app in `src/app`, not a nested Vite app.

```bash
cd ..
bun install
bun run dev --port 4000
```

Set `RECOVERAI_API_BASE_URL` if the API is not running at `http://127.0.0.1:8000`.

## Test

```bash
cd recover-ai/backend
pytest

cd ../..
bun run typecheck
bun run build
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/transactions` | List all transactions |
| GET | `/api/transactions/{id}` | Get transaction detail |
| GET | `/api/recovery-cases` | List recovery cases |
| GET | `/api/dashboard/summary` | Dashboard metrics |
| GET | `/api/risk/cases` | Risk cases (filterable) |
| GET | `/api/risk/cases/{id}` | Risk case detail |
| GET | `/api/risk/summary` | Risk summary metrics |
| POST | `/api/recovery-cases/{id}/diagnose` | Run AI diagnosis |
| GET | `/api/recovery-cases/{id}/diagnosis` | Get stored diagnosis |
| POST | `/api/recovery-cases/{id}/policy-check` | Run policy check |
| GET | `/api/recovery-cases/{id}/policy` | Get policy decision |
| POST | `/api/recovery-cases/{id}/execute` | Execute recovery action |
| GET | `/api/recovery-cases/{id}/actions` | Get execution history |
| POST | `/api/webhooks/razorpay` | Razorpay webhook (HMAC verified, idempotent) |
| GET | `/api/webhooks/events` | List recent webhook events (audit) |
| POST | `/api/evaluation/run` | Run simulated batch evaluation (SIMULATED) |
| GET | `/api/evaluation/latest` | Retrieve latest evaluation run |
