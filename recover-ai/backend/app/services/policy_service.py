"""Deterministic Policy Engine for RecoverAI.

Evaluates AI-recommended recovery actions against deterministic rules.
Never calls LLM. Never calls Razorpay. Purely rule-based.

The policy engine ensures that AI recommendations are independently
validated before any financial action is permitted.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from app.config import settings
from app.database import get_connection
from app.schemas.diagnosis import VALID_ACTIONS
from app.schemas.policy import (
    POLICY_VERSION,
    PolicyResult,
    RuleEvaluation,
)

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def evaluate_policy(case_id: str) -> dict:
    """Run deterministic policy evaluation on a recovery case.

    Requires an existing AI diagnosis. Returns a structured policy result
    with ALLOW or BLOCK decision and the rules evaluated.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT rc.*, t.customer_name, t.amount, t.currency, t.status AS transaction_status,
                   t.failure_reason, t.retry_count, t.previous_successful_payments,
                   t.customer_lifetime_value, t.hours_since_event, t.payment_method
            FROM recovery_cases rc
            JOIN transactions t ON t.id = rc.transaction_id
            WHERE rc.id = ?
            """,
            (case_id,),
        ).fetchone()

    if row is None:
        return {"decision": "error", "error": "Recovery case not found"}

    data = dict(row)

    # Check if AI diagnosis exists
    if data.get("diagnosis_status") != "completed":
        return {
            "decision": "BLOCK",
            "case_id": case_id,
            "action": data.get("recommended_action") or "UNKNOWN",
            "reason": "AI diagnosis not completed. Policy requires a valid diagnosis before evaluation.",
            "rules_evaluated": [
                RuleEvaluation(rule="diagnosis_exists", passed=False, detail=f"diagnosis_status={data.get('diagnosis_status', 'pending')}").model_dump()
            ],
            "policy_version": POLICY_VERSION,
            "evaluated_at": datetime.now(IST).isoformat(),
        }

    recommended_action = data.get("recommended_action")
    if recommended_action not in VALID_ACTIONS:
        return {
            "decision": "BLOCK",
            "case_id": case_id,
            "action": recommended_action or "UNKNOWN",
            "reason": f"Invalid recommended action: {recommended_action}",
            "rules_evaluated": [
                RuleEvaluation(rule="valid_action", passed=False, detail=f"action={recommended_action}").model_dump()
            ],
            "policy_version": POLICY_VERSION,
            "evaluated_at": datetime.now(IST).isoformat(),
        }

    # Evaluate action-specific rules
    rules_evaluated: list[dict] = []
    decision = "ALLOW"
    reason = ""

    if recommended_action == "RETRY_PAYMENT":
        decision, reason, rules_evaluated = _evaluate_retry_payment(data)
    elif recommended_action == "SEND_PAYMENT_LINK":
        decision, reason, rules_evaluated = _evaluate_send_payment_link(data)
    elif recommended_action == "CONTACT_CUSTOMER":
        decision, reason, rules_evaluated = _evaluate_contact_customer(data)
    elif recommended_action == "ESCALATE":
        decision, reason, rules_evaluated = _evaluate_escalate(data)
    elif recommended_action == "NO_ACTION":
        decision, reason, rules_evaluated = _evaluate_no_action(data)

    evaluated_at = datetime.now(IST).isoformat()

    # Persist the policy decision
    _persist_policy_decision(
        case_id=case_id,
        action=recommended_action,
        decision=decision,
        reason=reason,
        rules_evaluated=rules_evaluated,
        evaluated_at=evaluated_at,
    )

    return {
        "decision": decision,
        "case_id": case_id,
        "action": recommended_action,
        "reason": reason,
        "rules_evaluated": rules_evaluated,
        "policy_version": POLICY_VERSION,
        "evaluated_at": evaluated_at,
    }


def get_policy_decision(case_id: str) -> dict | None:
    """Retrieve the latest policy decision for a case."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM policy_decisions
            WHERE case_id = ?
            ORDER BY evaluated_at DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()

    if row is None:
        return None

    data = dict(row)
    try:
        rules = json.loads(data.get("rules_evaluated", "[]"))
    except (json.JSONDecodeError, TypeError):
        rules = []

    return {
        "case_id": data["case_id"],
        "action": data["action"],
        "decision": data["decision"],
        "reason": data["reason"],
        "rules_evaluated": rules,
        "policy_version": data["policy_version"],
        "evaluated_at": data["evaluated_at"],
    }


def _evaluate_retry_payment(data: dict) -> tuple[str, str, list[dict]]:
    """Evaluate RETRY_PAYMENT policy rules."""
    rules: list[dict] = []
    transaction_status = data.get("transaction_status")
    retry_count = data.get("retry_count", 0)
    risk_level = data.get("risk_level")
    amount = float(data.get("amount", 0))
    confidence = data.get("confidence", 0)

    # Rule 1: Transaction must be failed
    r1 = RuleEvaluation(
        rule="transaction_status_failed",
        passed=transaction_status == "failed",
        detail=f"transaction_status={transaction_status}",
    )
    rules.append(r1.model_dump())
    if not r1.passed:
        return "BLOCK", f"RETRY_PAYMENT requires failed transaction status, got {transaction_status}", rules

    # Rule 2: Retry count below threshold
    r2 = RuleEvaluation(
        rule="retry_count_below_threshold",
        passed=retry_count < settings.max_retry_count,
        detail=f"retry_count={retry_count}, max={settings.max_retry_count}",
    )
    rules.append(r2.model_dump())
    if not r2.passed:
        return "BLOCK", f"Retry count {retry_count} exceeds maximum {settings.max_retry_count}", rules

    # Rule 3: Risk level not HIGH
    r3 = RuleEvaluation(
        rule="risk_level_not_high",
        passed=risk_level != "HIGH",
        detail=f"risk_level={risk_level}",
    )
    rules.append(r3.model_dump())
    if not r3.passed:
        return "BLOCK", f"RETRY_PAYMENT blocked for HIGH risk cases (risk_level={risk_level})", rules

    # Rule 4: Amount within configured maximum
    r4 = RuleEvaluation(
        rule="amount_within_limit",
        passed=amount <= settings.max_retry_amount,
        detail=f"amount={amount}, max={settings.max_retry_amount}",
    )
    rules.append(r4.model_dump())
    if not r4.passed:
        return "BLOCK", f"Amount {amount} exceeds maximum retry amount {settings.max_retry_amount}", rules

    # Rule 5: AI confidence above threshold
    r5 = RuleEvaluation(
        rule="ai_confidence_above_threshold",
        passed=confidence is not None and confidence >= settings.min_ai_confidence,
        detail=f"confidence={confidence}, min={settings.min_ai_confidence}",
    )
    rules.append(r5.model_dump())
    if not r5.passed:
        return "BLOCK", f"AI confidence {confidence} below minimum threshold {settings.min_ai_confidence}", rules

    # Rule 6: Case eligible for recovery (status is pending_review)
    r6 = RuleEvaluation(
        rule="case_eligible",
        passed=data.get("status") == "pending_review",
        detail=f"status={data.get('status')}",
    )
    rules.append(r6.model_dump())
    if not r6.passed:
        return "BLOCK", f"Case not eligible for recovery (status={data.get('status')})", rules

    return "ALLOW", "All RETRY_PAYMENT rules satisfied", rules


def _evaluate_send_payment_link(data: dict) -> tuple[str, str, list[dict]]:
    """Evaluate SEND_PAYMENT_LINK policy rules."""
    rules: list[dict] = []
    transaction_status = data.get("transaction_status")
    risk_level = data.get("risk_level")
    amount = float(data.get("amount", 0))

    # Rule 1: Transaction must be abandoned or failed
    r1 = RuleEvaluation(
        rule="transaction_status_valid",
        passed=transaction_status in ("abandoned", "failed"),
        detail=f"transaction_status={transaction_status}",
    )
    rules.append(r1.model_dump())
    if not r1.passed:
        return "BLOCK", f"SEND_PAYMENT_LINK requires abandoned or failed status, got {transaction_status}", rules

    # Rule 2: Amount within configured limit
    r2 = RuleEvaluation(
        rule="amount_within_limit",
        passed=amount <= settings.max_payment_link_amount,
        detail=f"amount={amount}, max={settings.max_payment_link_amount}",
    )
    rules.append(r2.model_dump())
    if not r2.passed:
        return "BLOCK", f"Amount {amount} exceeds payment link limit {settings.max_payment_link_amount}", rules

    # Rule 3: Risk level not HIGH
    r3 = RuleEvaluation(
        rule="risk_level_not_high",
        passed=risk_level != "HIGH",
        detail=f"risk_level={risk_level}",
    )
    rules.append(r3.model_dump())
    if not r3.passed:
        return "BLOCK", f"SEND_PAYMENT_LINK blocked for HIGH risk cases (risk_level={risk_level})", rules

    # Rule 4: Case eligible for recovery
    r4 = RuleEvaluation(
        rule="case_eligible",
        passed=data.get("status") == "pending_review",
        detail=f"status={data.get('status')}",
    )
    rules.append(r4.model_dump())
    if not r4.passed:
        return "BLOCK", f"Case not eligible for recovery (status={data.get('status')})", rules

    return "ALLOW", "All SEND_PAYMENT_LINK rules satisfied", rules


def _evaluate_contact_customer(data: dict) -> tuple[str, str, list[dict]]:
    """Evaluate CONTACT_CUSTOMER policy rules."""
    rules: list[dict] = []
    transaction_status = data.get("transaction_status")

    # Rule 1: Transaction must be failed or abandoned
    r1 = RuleEvaluation(
        rule="transaction_status_valid",
        passed=transaction_status in ("failed", "abandoned"),
        detail=f"transaction_status={transaction_status}",
    )
    rules.append(r1.model_dump())
    if not r1.passed:
        return "BLOCK", f"CONTACT_CUSTOMER requires failed or abandoned status, got {transaction_status}", rules

    # Rule 2: Case eligible for recovery
    r2 = RuleEvaluation(
        rule="case_eligible",
        passed=data.get("status") == "pending_review",
        detail=f"status={data.get('status')}",
    )
    rules.append(r2.model_dump())
    if not r2.passed:
        return "BLOCK", f"Case not eligible for recovery (status={data.get('status')})", rules

    return "ALLOW", "All CONTACT_CUSTOMER rules satisfied", rules


def _evaluate_escalate(data: dict) -> tuple[str, str, list[dict]]:
    """Evaluate ESCALATE policy rules. Always ALLOW."""
    rules = [
        RuleEvaluation(rule="escalate_always_allowed", passed=True, detail="ESCALATE is always permitted").model_dump()
    ]
    return "ALLOW", "ESCALATE is always permitted", rules


def _evaluate_no_action(data: dict) -> tuple[str, str, list[dict]]:
    """Evaluate NO_ACTION policy rules. Always ALLOW."""
    rules = [
        RuleEvaluation(rule="no_action_always_allowed", passed=True, detail="NO_ACTION is always permitted").model_dump()
    ]
    return "ALLOW", "NO_ACTION is always permitted", rules


def _persist_policy_decision(
    case_id: str,
    action: str,
    decision: str,
    reason: str,
    rules_evaluated: list[dict],
    evaluated_at: str,
) -> None:
    """Persist a policy decision to the database."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO policy_decisions (case_id, action, decision, reason, rules_evaluated, policy_version, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (case_id, action, decision, reason, json.dumps(rules_evaluated), POLICY_VERSION, evaluated_at),
        )
        conn.commit()
