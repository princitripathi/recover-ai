from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class RecoveryCase:
    id: str
    transaction_id: str
    risk_score: int
    risk_level: str
    risk_factors: str
    recovery_priority: float
    root_cause: str | None
    recommended_action: str | None
    confidence: float | None
    diagnosis_reason: str | None
    diagnosis_status: str
    diagnosed_at: str | None
    status: str
    amount_recovered: Decimal
    created_at: datetime
