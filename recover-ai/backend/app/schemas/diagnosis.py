"""Pydantic models for AI diagnosis."""
from pydantic import BaseModel, Field


VALID_ROOT_CAUSES = [
    "TEMPORARY_PAYMENT_FAILURE",
    "INSUFFICIENT_FUNDS",
    "BANK_DECLINE",
    "CUSTOMER_ABANDONMENT",
    "UNKNOWN_FAILURE",
    "HIGH_RISK_TRANSACTION",
]

VALID_ACTIONS = [
    "RETRY_PAYMENT",
    "SEND_PAYMENT_LINK",
    "CONTACT_CUSTOMER",
    "ESCALATE",
    "NO_ACTION",
]


class DiagnosisResult(BaseModel):
    """Structured output from the AI diagnosis model."""
    root_cause: str = Field(description="Root cause category")
    recommended_action: str = Field(description="Recommended recovery action")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    reason: str = Field(description="Explanation of the diagnosis")
    risk_factors: list[str] = Field(description="Risk factors considered")


class DiagnosisResponse(BaseModel):
    """API response for diagnosis endpoint."""
    case_id: str
    root_cause: str
    recommended_action: str
    confidence: float
    reason: str
    risk_factors: list[str]
    diagnosis_status: str
    diagnosed_at: str | None = None
