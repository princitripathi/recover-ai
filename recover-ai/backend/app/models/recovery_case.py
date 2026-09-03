from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class RecoveryCase:
    id: str
    transaction_id: str
    risk_score: int
    root_cause: str | None
    recommended_action: str | None
    confidence: float | None
    status: str
    amount_recovered: Decimal
    created_at: datetime
