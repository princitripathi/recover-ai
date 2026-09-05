# RecoverAI Architecture

RecoverAI is intentionally split into small modules so later stages can add policy enforcement, Razorpay Test Mode integrations, recovery actions, outcome verification, metrics, and audit logging without rewriting the foundation.

## Current Flow

```text
Synthetic transaction CSV (520 records)
      -> SQLite database (with migration support)
      -> Transaction service
      -> Deterministic revenue-risk calculation
      -> Deterministic risk scoring engine
      -> Recovery case listing with risk levels
      -> Risk summary API
      -> Merchant dashboard with risk overview
```

## Stage 3 Flow — AI Diagnosis

```text
Recovery case selected by user
      -> POST /api/recovery-cases/{id}/diagnose
      -> Diagnosis service builds context from transaction + risk data
      -> Sends structured prompt to local LLM (Ollama)
      -> Parses and validates LLM JSON response (Pydantic)
      -> Persists diagnosis to recovery_cases table
      -> Returns structured diagnosis to frontend
      -> Frontend displays: root cause, action, confidence, explanation
```

## Stage 4 Flow — Deterministic Policy Engine

```text
AI diagnosis completed
      -> POST /api/recovery-cases/{id}/policy-check
      -> Policy service loads case + transaction + diagnosis data
      -> Evaluates deterministic rules for the recommended action
      -> Returns ALLOW or BLOCK with rules evaluated
      -> Persists policy decision to policy_decisions table
      -> Frontend displays: decision, reason, rules evaluated
```

## Stage 5 Flow — Razorpay Test Mode Execution

```text
Policy decision = ALLOW
      -> POST /api/recovery-cases/{id}/execute
      -> Execution service loads case + transaction + policy decision
      -> Verifies policy = ALLOW and action matches
      -> Checks Razorpay credentials are configured
      -> Calls Razorpay REST API to create payment link
      -> Persists execution result to recovery_actions table
      -> Returns: payment link URL, Razorpay reference, execution status
      -> Frontend displays: link created, reference, pending payment status
```

## Architecture Layers

```
Transaction
  -> Deterministic Risk Engine (score, level, factors)
    -> AI Diagnosis (root cause, recommended action, confidence)
      -> Policy Engine (deterministic: validates actions, ALLOW/BLOCK)
        -> Razorpay Executor (creates payment links after policy approval)
          -> Outcome Tracking (payment link lifecycle)
            -> Audit Trail (recovery_actions table)
```

## Boundaries

- `backend/app/database.py` owns SQLite schema creation, migrations, and demo seeding.
- `backend/app/services/` owns deterministic business calculations.
  - `risk_service.py` — risk scoring engine (no LLM, fully deterministic)
  - `diagnosis_service.py` — AI diagnosis via Ollama (LLM calls, prompt construction, response parsing)
  - `policy_service.py` — deterministic policy engine (no LLM, no Razorpay, rule-based)
  - `razorpay_service.py` — Razorpay HTTP client (REST API calls, no SDK dependency)
  - `execution_service.py` — execution orchestration (policy gate → Razorpay call → persist result)
  - `webhook_service.py` — HMAC verification, idempotent event handling, outcome state machine, amount attribution
  - `evaluation_service.py` — deterministic simulated evaluation over synthetic data (no Razorpay IO)
  - `transaction_service.py` — transaction queries
  - `recovery_service.py` — recovery case queries
  - `dashboard_service.py` — dashboard summary calculations
- `backend/app/routes/` exposes REST endpoints only.
- `src/services/recoverai-api.ts` isolates preview API calls from UI components.
- `src/app/api/[...path]/route.ts` proxies `GET|POST|PUT|PATCH|DELETE` to the FastAPI backend, preserving
  raw body and `X-Razorpay-Signature` for webhook HMAC verification.
- `src/app/page.tsx` renders the merchant-facing dashboard in the Ideavo preview, now including
  Outcome chain (Diagnosis → Policy → Execution → Outcome → Amount) and Simulated Evaluation card.

## Risk Scoring Model

The risk engine uses a weighted scoring model with 5 factors:

1. **Transaction Status** (0-35 points): Failed transactions score highest
2. **Transaction Amount** (0-20 points): Higher amounts increase risk
3. **Failure Reason** (0-20 points): Temporary failures score highest (recovery is more likely)
4. **Customer History** (0-16 points): Loyal customers have more revenue at stake
5. **Recency** (0-10 points): Recent events score higher (more actionable)

Risk levels: HIGH (80-100), MEDIUM (50-79), LOW (0-49)

Recovery priority combines revenue impact, recovery likelihood, and customer lifetime value into a 0.0-1.0 score.

## AI Diagnosis Design

### Why LLM for Diagnosis (But Not for Risk Scoring)

- Risk scoring must be deterministic, auditable, and reproducible — LLMs are not
- Root-cause analysis benefits from LLM pattern recognition across diverse failure scenarios
- Recovery action recommendations require understanding context that rigid rules cannot capture
- LLM responses are validated by Pydantic and constrained to controlled vocabularies

### LLM Configuration

- Provider: Ollama (local, no cloud dependency)
- Model: qwen2.5:3b (configurable via `RECOVERAI_OLLAMA_MODEL`)
- URL: configurable via `RECOVERAI_OLLAMA_URL`
- Timeout: configurable via `RECOVERAI_LLM_TIMEOUT`

### Prompt Design

The diagnosis prompt instructs the LLM to:
1. Use ONLY supplied transaction and risk information
2. Do not invent facts
3. Return structured JSON with controlled vocabulary
4. Never claim an action was executed
5. Financial actions will be validated by a separate policy engine

### Error Handling

- LLM unavailable -> `AI_UNAVAILABLE` status, API returns 200 with status
- Invalid JSON response -> `PARSE_ERROR` status, API returns 200 with status
- Unknown case -> 404 HTTP error
- Invalid root cause or action -> falls back to safe defaults

### Safety Design

- LLM receives only transaction/risk data — no secrets, no API keys
- LLM never directly calls Razorpay or any financial API
- LLM output is validated by Pydantic before persistence
- Diagnosis only RECOMMENDS actions — it does not EXECUTE them
- Policy engine validates recommendations before execution

## Policy Engine Design

### Why Deterministic Policy (Not LLM)

- Policy decisions must be auditable, reproducible, and predictable
- Financial safety requires deterministic rules, not probabilistic LLM output
- Policy engine is the final gatekeeper before any financial action
- LLM recommendation is never automatically executable

### Policy Rules

The policy engine evaluates 5 action types:

**RETRY_PAYMENT** — 6 rules:
1. Transaction status must be `failed`
2. Retry count must be below configured maximum
3. Risk level must not be HIGH
4. Amount must be within configured maximum retry amount
5. AI confidence must be above configured threshold
6. Case must be eligible for recovery (status=pending_review)

**SEND_PAYMENT_LINK** — 4 rules:
1. Transaction status must be `abandoned` or `failed`
2. Amount must be within configured maximum
3. Risk level must not be HIGH
4. Case must be eligible for recovery

**CONTACT_CUSTOMER** — 2 rules:
1. Transaction status must be `failed` or `abandoned`
2. Case must be eligible for recovery

**ESCALATE** — Always ALLOW (no rules)

**NO_ACTION** — Always ALLOW (no rules)

### Safety Design

- Completely deterministic — no LLM calls, no external API calls
- AI recommendation never automatically becomes executable
- Missing or unavailable diagnosis always results in BLOCK
- HIGH risk cases block all automated financial actions
- Policy decisions persisted to `policy_decisions` table for audit trail
- Configurable thresholds via environment variables

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RECOVERAI_MAX_RETRY_AMOUNT` | 25000.0 | Maximum INR amount for retry payment |
| `RECOVERAI_MAX_PAYMENT_LINK_AMOUNT` | 50000.0 | Maximum INR amount for payment link |
| `RECOVERAI_MIN_AI_CONFIDENCE` | 0.6 | Minimum AI confidence score (0.0-1.0) |
| `RECOVERAI_MAX_RETRY_COUNT` | 2 | Maximum retry attempts allowed |

## Razorpay Test Mode Integration

### Why Test Mode

- Test Mode allows full API integration without real money
- Payment links can be created and shared (customers see a test payment page)
- Webhook events fire for test payments, enabling full lifecycle testing
- No financial risk during development and demonstration

### Execution Safety

1. **Policy gate is mandatory** — BLOCK decisions never reach Razorpay
2. **Credentials are environment variables** — never hardcoded, never in API responses
3. **AI never calls Razorpay directly** — only the execution service does
4. **Payment link ≠ money recovered** — LINK_CREATED is not PAYMENT_SUCCESS
5. **Audit trail is complete** — every attempt recorded in `recovery_actions`

### Idempotency Strategy

Duplicate execution protection uses `case_id + action` as a uniqueness constraint:
- If a successful execution (LINK_CREATED, PAYMENT_PENDING, or PAYMENT_SUCCESS) already exists for a case+action, new attempts are blocked
- If the previous execution failed (EXECUTION_FAILED), retry is allowed
- This prevents accidental duplicate payment links for the same case

### Payment Link Lifecycle

```text
LINK_CREATED -> PAYMENT_PENDING -> PAYMENT_SUCCESS
                                  -> PAYMENT_FAILED
```

- `LINK_CREATED`: Razorpay API returned a payment link URL
- `PAYMENT_PENDING`: Customer has not yet completed payment
- `PAYMENT_SUCCESS`: Payment confirmed (via Razorpay webhook)
- `PAYMENT_FAILED`: Payment attempt failed

### Webhook Preparation

The architecture is prepared for Razorpay webhooks:
- `recovery_actions` table tracks execution status
- Status transitions (PAYMENT_PENDING → PAYMENT_SUCCESS) will be driven by verified webhook events
- Signature verification will be required for webhook processing
- Idempotent event processing prevents duplicate state changes

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RAZORPAY_KEY_ID` | (empty) | Razorpay Test Mode key ID |
| `RAZORPAY_KEY_SECRET` | (empty) | Razorpay Test Mode key secret |
| `RAZORPAY_BASE_URL` | `https://api.razorpay.com/v1` | Razorpay API base URL |

## Stage 6 Flow — Webhook Outcome + Measured Recovery

```text
Payment link created (LINK_CREATED)
      -> Customer pays (Razorpay)
        -> POST /api/webhooks/razorpay {event, payload, X-Razorpay-Signature}
          -> HMAC-SHA256 verify with RAZORPAY_WEBHOOK_SECRET; reject invalid
          -> Persist webhook_events (event_id UNIQUE, processing_status)
          -> If duplicate event_id → return 200 idempotent (no double apply)
          -> If event == payment.captured:
               find recovery_actions matching razorpay_reference / payment_link_id / notes.reference_id
               validate transition LINK_CREATED|PAYMENT_PENDING → PAYMENT_SUCCESS
               set recovery_actions.execution_status = PAYMENT_SUCCESS, completed_at
               set recovery_cases.amount_recovered = verified amount (paise→rupee), status=recovered
               set transactions.status = paid (captured)
               audit_logs entry; webhook_events = processed
          -> If event == payment.failed:
               set execution_status = PAYMENT_FAILED (do NOT increase amount_recovered)
               audit_logs entry; webhook_events = processed
          -> If unknown type → ignored but persisted; unknown reference → failed persisted
      -> Dashboard: AI Diagnosis ↓ Policy Decision ↓ Execution ↓ Outcome (amountRecovered only after verified success)

Simulated batch evaluation (no Razorpay IO):
  synthetic dataset (520) → deterministic risk already stored
    → deterministic diagnosis simulation → deterministic policy → stable-hash outcome
      → metrics (recovery_rate = recovered/at-risk, case_recovery_rate = succeeded/eligible)
        → persisted to evaluation_runs → GET /api/evaluation/latest
```

### Outcome State Machine

States: `LINK_CREATED`, `PAYMENT_PENDING` (optional intermediate), `PAYMENT_SUCCESS`, `PAYMENT_FAILED`,
`EXECUTION_FAILED`, `BLOCKED`. Only a verified `payment.captured` webhook may move
`LINK_CREATED`/`PAYMENT_PENDING` → `PAYMENT_SUCCESS`; `payment.failed` → `PAYMENT_FAILED`.
Direct transitions without a webhook are blocked in the service layer. Idempotency uses both
`webhook_events.event_id` uniqueness and a guard against double-increment of `amount_recovered`.

### Webhook Service

- File: `services/webhook_service.py` (HMAC verify, event parsing, recovery_action lookup,
  transition guards, amount handling via Razorpay paise, transaction/case updates, audit_logs).
- Route: `routes/webhooks.py` — `POST /api/webhooks/razorpay` (reads raw body for HMAC,
  returns 400 for missing/invalid signature, 200 for all other verified outcomes including
  duplicate/ignored/failed reference), plus `GET /api/webhooks/events` for audit.
- Table: `webhook_events(id, event_id UNIQUE, event_type, payload, processing_status,
  received_at, processed_at, error_message, razorpay_reference)`.
- Config: `RECOVERAI_RAZORPAY_WEBHOOK_SECRET` (or RAZORPAY_WEBHOOK_SECRET) — never exposed.

### Evaluation Service

- File: `services/evaluation_service.py` — deterministic `run_evaluation()` and `get_latest_evaluation()`.
- Route: `routes/evaluation.py` — `POST /api/evaluation/run` (SIMULATED, persisted), `GET /api/evaluation/latest`.
- Table: `evaluation_runs` (dataset_size, revenue_at_risk, amount_recovered, recovery_rate,
  case_recovery_rate, policy_blocked/allowed, baseline_recovered, details JSON, created_at).
- See `docs/evaluation.md` for methodology, formulas, simulated vs real distinction, limitations, and example.

## Deferred Stages

The following are not implemented yet by design:

- RETRY_PAYMENT live execution (Razorpay Orders API)
- Contact customer execution (future stage)
- Authentication and merchant accounts

## Demo Data

All data is synthetic and used only for local demonstration. It must not be represented as real merchant data.
