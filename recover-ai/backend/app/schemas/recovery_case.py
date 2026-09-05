from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class RecoveryCaseOut(BaseModel):
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
    root_cause: str | None = None
    recommended_action: str | None = None
    confidence: float | None = None
    diagnosis_reason: str | None = None
    diagnosis_status: str = "pending"
    diagnosed_at: str | None = None
    status: str
    amount_recovered: Decimal = Field(max_digits=12, decimal_places=2)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
