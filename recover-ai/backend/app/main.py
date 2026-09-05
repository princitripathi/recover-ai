from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routes import dashboard, health, recovery_cases, transactions, risk, diagnosis, policy, execution, webhooks, evaluation


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="RecoverAI API",
    description="Synthetic demo API for revenue risk detection foundations.",
    version="0.6.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(transactions.router)
app.include_router(recovery_cases.router)
app.include_router(dashboard.router)
app.include_router(risk.router)
app.include_router(diagnosis.router)
app.include_router(policy.router)
app.include_router(execution.router)
app.include_router(webhooks.router)
app.include_router(evaluation.router)
