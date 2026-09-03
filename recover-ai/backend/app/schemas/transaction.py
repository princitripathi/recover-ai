from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

TransactionStatus = Literal["paid", "failed", "abandoned", "pending"]


class TransactionOut(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    currency: str
    status: TransactionStatus
    payment_method: str
    failure_reason: str | None = None
    created_at: datetime
    is_revenue_at_risk: bool

    model_config = ConfigDict(from_attributes=True)
