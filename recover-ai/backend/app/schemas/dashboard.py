from decimal import Decimal
from pydantic import BaseModel, Field


class DashboardSummary(BaseModel):
    total_transactions: int
    revenue_processed: Decimal = Field(max_digits=14, decimal_places=2)
    revenue_at_risk: Decimal = Field(max_digits=14, decimal_places=2)
    failed_transaction_count: int
    abandoned_transaction_count: int
    recovery_cases: int
    revenue_recovered: Decimal = Field(max_digits=14, decimal_places=2)
    recovery_rate: float
    cases_to_review: int
