"""Pydantic models for recovery action execution."""
from pydantic import BaseModel, Field

VALID_EXECUTION_STATUSES = [
    "BLOCKED",
    "LINK_CREATED",
    "PAYMENT_PENDING",
    "PAYMENT_SUCCESS",
    "PAYMENT_FAILED",
    "EXECUTION_FAILED",
]


class ExecuteRequest(BaseModel):
    """Request body for the execute endpoint."""
    action: str = Field(description="The action to execute (must match policy-approved action)")


class ExecutionResult(BaseModel):
    """Structured output from the execution service."""
    case_id: str
    action: str
    execution_status: str
    policy_decision: str
    policy_decision_id: int | None = None
    razorpay_called: bool = False
    razorpay_reference: str | None = None
    payment_link_id: str | None = None
    payment_link_url: str | None = None
    message: str
    created_at: str


class ExecutionHistoryItem(BaseModel):
    """A single execution history record."""
    id: int
    case_id: str
    action: str
    execution_status: str
    razorpay_reference: str | None = None
    payment_link_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    completed_at: str | None = None
