"""Deterministic risk scoring engine for RecoverAI.

Calculates revenue recovery risk scores using a weighted model based on
transaction attributes. No LLM or AI is involved — every score is fully
deterministic and explainable.

Risk Score (0-100):
  - Transaction status contribution (0-35)
  - Amount contribution (0-20)
  - Failure reason contribution (0-20)
  - Customer history contribution (0-15)
  - Recency contribution (0-10)

Risk Levels:
  - HIGH:   80-100
  - MEDIUM: 50-79
  - LOW:    0-49

Recovery Priority (0.0 - 1.0):
  Combines recovery likelihood (customer history + temporary failures)
  with revenue at risk (amount + risk score).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

AT_RISK_STATUSES = {"failed", "abandoned"}

# Failure reasons grouped by severity
TEMPORARY_FAILURES = {
    "bank_downtime", "network_error", "checkout_timeout",
    "authorization_pending", "bank_processing", "waiting_for_verification",
}
CUSTOMER_SIDE_FAILURES = {
    "insufficient_funds", "customer_inactive", "transaction_limit_exceeded",
}
PERMANENT_FAILURES = {
    "card_expired", "expired_card", "vpa_invalid",
}
SYSTEM_FAILURES = {
    "issuer_declined", "do_not_honor", "generic_decline",
    "authentication_failed", "suspected_fraud", "invalid_amount",
    "duplicate_transaction",
}


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: int
    risk_level: str
    risk_factors: list[str]
    recovery_priority: float


def calculate_risk(
    status: str,
    amount: Decimal,
    retry_count: int,
    previous_successful_payments: int,
    customer_lifetime_value: Decimal,
    hours_since_event: int,
    failure_reason: str | None,
) -> RiskAssessment:
    """Calculate deterministic risk score and recovery priority for a transaction."""

    risk_factors: list[str] = []
    score = 0.0

    # --- 1. Transaction Status (0-35 points) ---
    if status == "failed":
        score += 33
        risk_factors.append("Failed transaction")
    elif status == "abandoned":
        score += 25
        risk_factors.append("Abandoned checkout")
    elif status == "pending":
        score += 10
        risk_factors.append("Pending transaction")
    else:
        # Paid — should not create a recovery case, but handle gracefully
        score += 0

    # --- 2. Amount contribution (0-20 points) ---
    if amount >= Decimal("50000"):
        score += 20
        risk_factors.append("Very high-value transaction (>=50k)")
    elif amount >= Decimal("25000"):
        score += 16
        risk_factors.append("High-value transaction (>=25k)")
    elif amount >= Decimal("10000"):
        score += 12
        risk_factors.append("Above-average transaction (>=10k)")
    elif amount >= Decimal("5000"):
        score += 8
        risk_factors.append("Moderate transaction amount")
    elif amount >= Decimal("2000"):
        score += 4
        risk_factors.append("Small-moderate transaction amount")
    else:
        score += 1
        risk_factors.append("Low transaction amount")

    # --- 3. Failure Reason (0-22 points) ---
    if failure_reason:
        if failure_reason in TEMPORARY_FAILURES:
            score += 20
            risk_factors.append(f"Temporary-looking failure: {failure_reason}")
        elif failure_reason in CUSTOMER_SIDE_FAILURES:
            score += 13
            risk_factors.append(f"Customer-side issue: {failure_reason}")
        elif failure_reason in PERMANENT_FAILURES:
            score += 6
            risk_factors.append(f"Permanent failure: {failure_reason}")
        elif failure_reason in SYSTEM_FAILURES:
            score += 15
            risk_factors.append(f"System/bank failure: {failure_reason}")
        else:
            score += 10
            risk_factors.append(f"Unclassified failure: {failure_reason}")
    else:
        if status == "abandoned":
            score += 10
            risk_factors.append("No failure reason recorded (abandoned)")

    # --- 4. Customer History (0-16 points) ---
    if previous_successful_payments >= 10:
        score += 16
        risk_factors.append("Loyal customer (10+ prior payments)")
    elif previous_successful_payments >= 5:
        score += 12
        risk_factors.append("Returning customer (5+ prior payments)")
    elif previous_successful_payments >= 2:
        score += 8
        risk_factors.append("Repeat customer (2-4 prior payments)")
    elif previous_successful_payments == 1:
        score += 4
        risk_factors.append("One prior successful payment")
    else:
        score += 1
        risk_factors.append("First-time customer")

    # --- 5. Recency (0-10 points) ---
    if hours_since_event <= 6:
        score += 10
        risk_factors.append("Very recent event (<=6h)")
    elif hours_since_event <= 24:
        score += 8
        risk_factors.append("Recent event (<=24h)")
    elif hours_since_event <= 72:
        score += 6
        risk_factors.append("Within 3 days")
    elif hours_since_event <= 168:
        score += 4
        risk_factors.append("Within 1 week")
    elif hours_since_event <= 336:
        score += 2
        risk_factors.append("Within 2 weeks")
    else:
        score += 0
        risk_factors.append("Older than 2 weeks")

    # --- 6. Retry Count (inverted: fewer retries = higher risk) ---
    # No explicit score contribution; retry_count affects recovery_priority below.

    # Clamp score to 0-100
    risk_score = max(0, min(100, round(score)))

    # Determine risk level
    if risk_score >= 80:
        risk_level = "HIGH"
    elif risk_score >= 50:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # --- Recovery Priority (0.0 - 1.0) ---
    recovery_priority = _calculate_recovery_priority(
        risk_score=risk_score,
        amount=amount,
        previous_successful_payments=previous_successful_payments,
        customer_lifetime_value=customer_lifetime_value,
        failure_reason=failure_reason,
        hours_since_event=hours_since_event,
        retry_count=retry_count,
    )

    return RiskAssessment(
        risk_score=risk_score,
        risk_level=risk_level,
        risk_factors=risk_factors,
        recovery_priority=recovery_priority,
    )


def _calculate_recovery_priority(
    risk_score: int,
    amount: Decimal,
    previous_successful_payments: int,
    customer_lifetime_value: Decimal,
    failure_reason: str | None,
    hours_since_event: int,
    retry_count: int,
) -> float:
    """Calculate recovery priority combining likelihood and revenue impact.

    Priority = 0.5 * revenue_impact + 0.3 * likelihood + 0.2 * customer_value

    Each component is normalized to 0.0 - 1.0.
    """
    # Revenue impact: normalized amount (cap at 50k = 1.0)
    revenue_impact = min(float(amount) / 50000.0, 1.0)

    # Recovery likelihood: based on customer history, failure type, recency
    likelihood = 0.0

    # Customer history contribution (0.0 - 0.4)
    if previous_successful_payments >= 10:
        likelihood += 0.4
    elif previous_successful_payments >= 5:
        likelihood += 0.3
    elif previous_successful_payments >= 2:
        likelihood += 0.2
    elif previous_successful_payments >= 1:
        likelihood += 0.1

    # Failure type contribution (0.0 - 0.3)
    if failure_reason in TEMPORARY_FAILURES:
        likelihood += 0.3
    elif failure_reason in CUSTOMER_SIDE_FAILURES:
        likelihood += 0.2
    elif failure_reason in SYSTEM_FAILURES:
        likelihood += 0.15

    # Recency contribution (0.0 - 0.2)
    if hours_since_event <= 24:
        likelihood += 0.2
    elif hours_since_event <= 72:
        likelihood += 0.15
    elif hours_since_event <= 168:
        likelihood += 0.1
    elif hours_since_event <= 336:
        likelihood += 0.05

    # Retry penalty (0.0 - 0.1)
    if retry_count == 0:
        likelihood += 0.1
    elif retry_count <= 2:
        likelihood += 0.05

    likelihood = min(likelihood, 1.0)

    # Customer lifetime value: normalized (cap at 200k = 1.0)
    clv_norm = min(float(customer_lifetime_value) / 200000.0, 1.0)

    priority = 0.5 * revenue_impact + 0.3 * likelihood + 0.2 * clv_norm
    return round(min(priority, 1.0), 4)


def risk_level_from_score(score: int) -> str:
    if score >= 80:
        return "HIGH"
    elif score >= 50:
        return "MEDIUM"
    return "LOW"


def assess_transaction(row: dict) -> RiskAssessment:
    """Convenience wrapper to assess a transaction from a database row dict."""
    return calculate_risk(
        status=row["status"],
        amount=Decimal(str(row["amount"])),
        retry_count=int(row.get("retry_count", 0)),
        previous_successful_payments=int(row.get("previous_successful_payments", 0)),
        customer_lifetime_value=Decimal(str(row.get("customer_lifetime_value", "0"))),
        hours_since_event=int(row.get("hours_since_event", 0)),
        failure_reason=row.get("failure_reason"),
    )
