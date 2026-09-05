"""Pydantic models for deterministic policy engine."""
from datetime import datetime
from pydantic import BaseModel, Field

POLICY_VERSION = "1.0.0"

VALID_DECISIONS = ["ALLOW", "BLOCK"]


class RuleEvaluation(BaseModel):
    """A single rule that was evaluated."""
    rule: str
    passed: bool
    detail: str


class PolicyResult(BaseModel):
    """Structured output from the deterministic policy engine."""
    case_id: str
    action: str
    decision: str = Field(description="ALLOW or BLOCK")
    reason: str
    rules_evaluated: list[RuleEvaluation]
    policy_version: str
    evaluated_at: str


class PolicyResponse(BaseModel):
    """API response for policy check endpoint."""
    case_id: str
    action: str
    decision: str
    reason: str
    rules_evaluated: list[RuleEvaluation]
    policy_version: str
    evaluated_at: str
