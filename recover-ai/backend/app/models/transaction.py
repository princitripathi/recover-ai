from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Transaction:
    id: str
    customer_id: str
    customer_name: str
    amount: Decimal
    currency: str
    status: str
    payment_method: str
    failure_reason: str | None
    created_at: datetime
