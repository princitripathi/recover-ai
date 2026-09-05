import json
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_connection

router = APIRouter(prefix="/api/risk", tags=["risk"])

VALID_SORT_FIELDS = {"risk_score", "amount", "recovery_priority", "created_at", "risk_level"}
VALID_ORDERS = {"asc", "desc"}


class RiskCaseItem(BaseModel):
    id: str
    transaction_id: str
    customer_name: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    transaction_status: str | None = None
    failure_reason: str | None = None
    retry_count: int | None = None
    previous_successful_payments: int | None = None
    customer_lifetime_value: Decimal | None = None
    hours_since_event: int | None = None
    risk_score: int = Field(ge=0, le=100)
    risk_level: str
    risk_factors: str = "[]"
    recovery_priority: float = 0.0
    status: str
    amount_recovered: Decimal = Field(max_digits=12, decimal_places=2)
    created_at: str


class RiskCaseDetail(RiskCaseItem):
    root_cause: str | None = None
    recommended_action: str | None = None
    confidence: float | None = None
    diagnosis_reason: str | None = None
    diagnosis_status: str = "pending"
    diagnosed_at: str | None = None


class RiskSummary(BaseModel):
    total_risk_cases: int
    high_risk_cases: int
    medium_risk_cases: int
    low_risk_cases: int
    revenue_at_risk: Decimal = Field(max_digits=14, decimal_places=2)
    high_risk_revenue: Decimal = Field(max_digits=14, decimal_places=2)
    medium_risk_revenue: Decimal = Field(max_digits=14, decimal_places=2)
    low_risk_revenue: Decimal = Field(max_digits=14, decimal_places=2)
    average_risk_score: float
    recovery_priority_high: int


def _row_to_case_item(row) -> RiskCaseItem:
    data = dict(row)
    return RiskCaseItem(
        id=data["id"],
        transaction_id=data["transaction_id"],
        customer_name=data.get("customer_name"),
        amount=Decimal(str(data["amount"])) if data.get("amount") is not None else None,
        currency=data.get("currency"),
        transaction_status=data.get("transaction_status"),
        failure_reason=data.get("failure_reason"),
        retry_count=data.get("retry_count"),
        previous_successful_payments=data.get("previous_successful_payments"),
        customer_lifetime_value=Decimal(str(data["customer_lifetime_value"])) if data.get("customer_lifetime_value") is not None else None,
        hours_since_event=data.get("hours_since_event"),
        risk_score=data["risk_score"],
        risk_level=data["risk_level"],
        risk_factors=data.get("risk_factors", "[]"),
        recovery_priority=data.get("recovery_priority", 0.0),
        status=data["status"],
        amount_recovered=Decimal(str(data["amount_recovered"])),
        created_at=data["created_at"],
    )


def _row_to_case_detail(row) -> RiskCaseDetail:
    item = _row_to_case_item(row)
    data = dict(row)
    return RiskCaseDetail(
        **item.model_dump(),
        root_cause=data.get("root_cause"),
        recommended_action=data.get("recommended_action"),
        confidence=data.get("confidence"),
        diagnosis_reason=data.get("diagnosis_reason"),
        diagnosis_status=data.get("diagnosis_status", "pending"),
        diagnosed_at=data.get("diagnosed_at"),
    )


SELECT_WITH_JOINS = """
    SELECT rc.*, t.customer_name, t.amount, t.currency, t.status AS transaction_status,
           t.failure_reason, t.retry_count, t.previous_successful_payments,
           t.customer_lifetime_value, t.hours_since_event
    FROM recovery_cases rc
    JOIN transactions t ON t.id = rc.transaction_id
"""


@router.get("/cases", response_model=list[RiskCaseItem])
def list_risk_cases(
    risk_level: Literal["HIGH", "MEDIUM", "LOW"] | None = Query(None, description="Filter by risk level"),
    sort_by: str = Query("risk_score", description="Sort field"),
    order: str = Query("desc", description="Sort order: asc or desc"),
):
    if sort_by not in VALID_SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by. Must be one of: {', '.join(sorted(VALID_SORT_FIELDS))}")
    if order not in VALID_ORDERS:
        raise HTTPException(status_code=400, detail="Invalid order. Must be 'asc' or 'desc'.")

    query = SELECT_WITH_JOINS
    params: list = []

    if risk_level:
        query += " WHERE rc.risk_level = ?"
        params.append(risk_level)

    # Risk level has custom sort order, handle it specially
    if sort_by == "risk_level":
        order_clause = f"CASE rc.risk_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 END {'ASC' if order == 'asc' else 'DESC'}"
        query += f" ORDER BY {order_clause}, rc.created_at DESC"
    else:
        sort_column = f"rc.{sort_by}" if sort_by in {"risk_score", "recovery_priority", "created_at"} else f"t.{sort_by}"
        query += f" ORDER BY {sort_column} {order.upper()}, rc.created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_case_item(row) for row in rows]


@router.get("/cases/{case_id}", response_model=RiskCaseDetail)
def get_risk_case(case_id: str):
    query = SELECT_WITH_JOINS + " WHERE rc.id = ?"
    with get_connection() as conn:
        row = conn.execute(query, (case_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    return _row_to_case_detail(row)


@router.get("/summary", response_model=RiskSummary)
def risk_summary():
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM recovery_cases").fetchone()[0]
        high = conn.execute("SELECT COUNT(*) FROM recovery_cases WHERE risk_level = 'HIGH'").fetchone()[0]
        medium = conn.execute("SELECT COUNT(*) FROM recovery_cases WHERE risk_level = 'MEDIUM'").fetchone()[0]
        low = conn.execute("SELECT COUNT(*) FROM recovery_cases WHERE risk_level = 'LOW'").fetchone()[0]

        rev_at_risk = conn.execute(
            "SELECT COALESCE(SUM(CAST(t.amount AS REAL)), 0) FROM recovery_cases rc JOIN transactions t ON t.id = rc.transaction_id"
        ).fetchone()[0]
        high_rev = conn.execute(
            "SELECT COALESCE(SUM(CAST(t.amount AS REAL)), 0) FROM recovery_cases rc JOIN transactions t ON t.id = rc.transaction_id WHERE rc.risk_level = 'HIGH'"
        ).fetchone()[0]
        med_rev = conn.execute(
            "SELECT COALESCE(SUM(CAST(t.amount AS REAL)), 0) FROM recovery_cases rc JOIN transactions t ON t.id = rc.transaction_id WHERE rc.risk_level = 'MEDIUM'"
        ).fetchone()[0]
        low_rev = conn.execute(
            "SELECT COALESCE(SUM(CAST(t.amount AS REAL)), 0) FROM recovery_cases rc JOIN transactions t ON t.id = rc.transaction_id WHERE rc.risk_level = 'LOW'"
        ).fetchone()[0]

        avg_score = conn.execute("SELECT COALESCE(AVG(risk_score), 0) FROM recovery_cases").fetchone()[0]
        high_priority = conn.execute("SELECT COUNT(*) FROM recovery_cases WHERE recovery_priority >= 0.6").fetchone()[0]

    return RiskSummary(
        total_risk_cases=total,
        high_risk_cases=high,
        medium_risk_cases=medium,
        low_risk_cases=low,
        revenue_at_risk=Decimal(str(rev_at_risk)).quantize(Decimal("0.01")),
        high_risk_revenue=Decimal(str(high_rev)).quantize(Decimal("0.01")),
        medium_risk_revenue=Decimal(str(med_rev)).quantize(Decimal("0.01")),
        low_risk_revenue=Decimal(str(low_rev)).quantize(Decimal("0.01")),
        average_risk_score=round(float(avg_score), 2),
        recovery_priority_high=high_priority,
    )
