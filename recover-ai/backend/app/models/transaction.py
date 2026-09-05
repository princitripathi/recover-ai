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
    retry_count: int
    previous_successful_payments: int
    customer_lifetime_value: Decimal
    hours_since_event: int
    checkout_session_id: str | None
