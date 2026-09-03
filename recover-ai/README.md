# RecoverAI

RecoverAI is an AI-powered Revenue Recovery platform foundation for merchants. It identifies deterministic revenue at risk from payment events, presents recovery cases for review, and keeps clean module boundaries for future AI diagnosis, policy enforcement, Razorpay Test Mode, recovery execution, and outcome tracking.

This version is a synthetic demo environment only. It does not use real merchant data, does not integrate Razorpay APIs, does not include authentication, and does not generate fake AI responses.

## Implemented Functionality

- Next.js React frontend used by the Ideavo preview
- FastAPI REST API with SQLite persistence
- Synthetic transaction seeding from `data/demo_transactions.csv`
- Transaction and recovery-case data models
- Deterministic revenue-at-risk calculation: failed + abandoned transaction amounts
- Dashboard summary metrics calculated from the database
- Responsive React merchant dashboard with KPI cards, recovery cases, and transaction detail view
- Backend tests for health, transaction retrieval, dashboard summary, and revenue-at-risk calculation

## Tech Stack

- Frontend: React with Next.js App Router, TypeScript
- Backend: Python, FastAPI, Pydantic
- Database: SQLite with a simple service/database layer
- Tests: pytest and FastAPI TestClient

## Project Structure

```text
recover-ai/
  backend/
    app/
      main.py
      config.py
      database.py
      models/
      schemas/
      routes/
      services/
    tests/
    requirements.txt
  data/demo_transactions.csv
  docs/architecture.md
  README.md
  .env.example
  .gitignore
```

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
bun run build
```
