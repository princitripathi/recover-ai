# RecoverAI Architecture

RecoverAI is intentionally split into small modules so later stages can add AI diagnosis, Razorpay Test Mode integrations, policy enforcement, recovery actions, outcome verification, metrics, and audit logging without rewriting the foundation.

## Current Flow

```text
Synthetic transaction CSV
      -> SQLite database
      -> Transaction service
      -> Deterministic revenue-risk calculation
      -> Recovery case listing
      -> Merchant dashboard
```

## Boundaries

- `backend/app/database.py` owns SQLite schema creation and demo seeding.
- `backend/app/services/` owns deterministic business calculations.
- `backend/app/routes/` exposes REST endpoints only.
- `src/services/recoverai-api.ts` isolates preview API calls from UI components.
- `src/app/page.tsx` renders the merchant-facing dashboard in the Ideavo preview.

## Deferred Stages

The following are not implemented yet by design:

- AI diagnosis and root cause analysis
- Razorpay API integration
- Authentication and merchant accounts
- Policy engine enforcement
- Recovery action execution
- Outcome verification and audit logs

## Demo Data

All data is synthetic and used only for local demonstration. It must not be represented as real merchant data.
