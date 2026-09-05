"""Execution service for RecoverAI.

Orchestrates the full recovery action execution flow:
1. Load recovery case + transaction
2. Verify policy decision = ALLOW
3. Verify action match
4. Execute via Razorpay (if applicable)
5. Persist execution result
6. Return structured response

Never bypasses the policy engine.
Never calls Razorpay without ALLOW decision.
Never marks money as recovered until actual payment success.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from app.config import settings
from app.database import get_connection
from app.services.razorpay_service import create_payment_link, has_credentials, RazorpayAPIError
from app.schemas.execution import ExecutionResult

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def execute_recovery_action(case_id: str, requested_action: str) -> dict:
    """Execute a recovery action after verifying policy gate.

    The backend independently:
    - retrieves the stored AI diagnosis
    - retrieves the latest policy decision
    - verifies policy = ALLOW
    - verifies action match
    - executes only if all checks pass
    """
    now = datetime.now(IST).isoformat()

    # Step 1: Load case + transaction
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT rc.*, t.customer_name, t.amount, t.currency, t.status AS transaction_status,
                   t.failure_reason, t.retry_count, t.previous_successful_payments,
                   t.customer_lifetime_value, t.hours_since_event, t.payment_method,
                   t.customer_id, t.checkout_session_id
            FROM recovery_cases rc
            JOIN transactions t ON t.id = rc.transaction_id
            WHERE rc.id = ?
            """,
            (case_id,),
        ).fetchone()

    if row is None:
        return _blocked_result(
            case_id, requested_action,
            "Recovery case not found",
            now,
        )

    case_data = dict(row)

    # Step 2: Check idempotency — block if successful execution already exists
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, execution_status FROM recovery_actions
            WHERE case_id = ? AND action = ? AND execution_status IN ('LINK_CREATED', 'PAYMENT_PENDING', 'PAYMENT_SUCCESS')
            LIMIT 1
            """,
            (case_id, requested_action),
        ).fetchone()

    if existing is not None:
        return _blocked_result(
            case_id, requested_action,
            f"Duplicate execution blocked: a successful {requested_action} already exists (action_id={existing['id']}, status={existing['execution_status']})",
            now,
        )

    # Step 3: Get latest policy decision
    policy_decision = _get_latest_policy_decision(case_id)

    if policy_decision is None:
        action_id = _persist_execution(
            case_id=case_id,
            action=requested_action,
            policy_decision_id=None,
            execution_status="BLOCKED",
            error_message="No policy decision found. Run policy check first.",
            created_at=now,
        )
        return {
            "case_id": case_id,
            "action": requested_action,
            "execution_status": "BLOCKED",
            "policy_decision": "NONE",
            "policy_decision_id": None,
            "razorpay_called": False,
            "razorpay_reference": None,
            "payment_link_id": None,
            "payment_link_url": None,
            "message": "No policy decision found. Run policy check first.",
            "created_at": now,
        }

    # Step 4: Verify policy = ALLOW
    if policy_decision["decision"] != "ALLOW":
        action_id = _persist_execution(
            case_id=case_id,
            action=requested_action,
            policy_decision_id=policy_decision.get("id"),
            execution_status="BLOCKED",
            error_message=f"Policy decision: {policy_decision['decision']}. Reason: {policy_decision['reason']}",
            created_at=now,
        )
        return {
            "case_id": case_id,
            "action": requested_action,
            "execution_status": "BLOCKED",
            "policy_decision": policy_decision["decision"],
            "policy_decision_id": policy_decision.get("id"),
            "razorpay_called": False,
            "razorpay_reference": None,
            "payment_link_id": None,
            "payment_link_url": None,
            "message": f"Policy decision: {policy_decision['decision']}. Reason: {policy_decision['reason']}",
            "created_at": now,
        }

    # Step 5: Verify action match
    if policy_decision["action"] != requested_action:
        action_id = _persist_execution(
            case_id=case_id,
            action=requested_action,
            policy_decision_id=policy_decision.get("id"),
            execution_status="BLOCKED",
            error_message=f"Action mismatch: policy approved {policy_decision['action']}, requested {requested_action}",
            created_at=now,
        )
        return {
            "case_id": case_id,
            "action": requested_action,
            "execution_status": "BLOCKED",
            "policy_decision": "ALLOW",
            "policy_decision_id": policy_decision.get("id"),
            "razorpay_called": False,
            "razorpay_reference": None,
            "payment_link_id": None,
            "payment_link_url": None,
            "message": f"Action mismatch: policy approved {policy_decision['action']}, requested {requested_action}",
            "created_at": now,
        }

    # Step 6: Check Razorpay credentials
    if not has_credentials():
        action_id = _persist_execution(
            case_id=case_id,
            action=requested_action,
            policy_decision_id=policy_decision.get("id"),
            execution_status="EXECUTION_FAILED",
            error_message="Razorpay credentials not configured.",
            created_at=now,
            completed_at=now,
        )
        return {
            "case_id": case_id,
            "action": requested_action,
            "execution_status": "EXECUTION_FAILED",
            "policy_decision": "ALLOW",
            "policy_decision_id": policy_decision.get("id"),
            "razorpay_called": False,
            "razorpay_reference": None,
            "payment_link_id": None,
            "payment_link_url": None,
            "message": "Razorpay credentials not configured.",
            "created_at": now,
        }

    # Step 7: Execute — create payment link via Razorpay
    if requested_action == "SEND_PAYMENT_LINK":
        return _execute_send_payment_link(
            case_data=case_data,
            policy_decision=policy_decision,
            now=now,
        )

    # Unknown action for execution
    action_id = _persist_execution(
        case_id=case_id,
        action=requested_action,
        policy_decision_id=policy_decision.get("id"),
        execution_status="EXECUTION_FAILED",
        error_message=f"Action {requested_action} is not supported for execution yet.",
        created_at=now,
        completed_at=now,
    )
    return {
        "case_id": case_id,
        "action": requested_action,
        "execution_status": "EXECUTION_FAILED",
        "policy_decision": "ALLOW",
        "policy_decision_id": policy_decision.get("id"),
        "razorpay_called": False,
        "razorpay_reference": None,
        "payment_link_id": None,
        "payment_link_url": None,
        "message": f"Action {requested_action} is not supported for execution yet.",
        "created_at": now,
    }


def _execute_send_payment_link(
    case_data: dict,
    policy_decision: dict,
    now: str,
) -> dict:
    """Execute SEND_PAYMENT_LINK via Razorpay."""
    case_id = case_data["id"]
    amount = float(case_data["amount"])
    currency = case_data.get("currency", "INR")
    customer_name = case_data.get("customer_name", "Customer")

    # Razorpay expects amount in paise (smallest currency unit)
    amount_paise = int(amount * 100)

    # Build reference ID for idempotency
    reference_id = f"RC-{case_id}-SPL-{int(datetime.now(IST).timestamp())}"

    description = f"Recovery payment for case {case_id} | Transaction {case_data.get('transaction_id', 'N/A')}"

    try:
        result = create_payment_link(
            amount_paise=amount_paise,
            currency=currency,
            customer_name=customer_name,
            customer_email=None,
            customer_contact=None,
            description=description,
            reference_id=reference_id,
        )

        razorpay_id = result.get("id", "")
        short_url = result.get("short_url", "")

        action_id = _persist_execution(
            case_id=case_id,
            action="SEND_PAYMENT_LINK",
            policy_decision_id=policy_decision.get("id"),
            execution_status="LINK_CREATED",
            razorpay_reference=razorpay_id,
            payment_link_id=razorpay_id,
            payment_link_url=short_url,
            created_at=now,
            completed_at=now,
        )

        return {
            "case_id": case_id,
            "action": "SEND_PAYMENT_LINK",
            "execution_status": "LINK_CREATED",
            "policy_decision": "ALLOW",
            "policy_decision_id": policy_decision.get("id"),
            "razorpay_called": True,
            "razorpay_reference": razorpay_id,
            "payment_link_id": razorpay_id,
            "payment_link_url": short_url,
            "message": f"Payment link created successfully. Share URL: {short_url}",
            "created_at": now,
        }

    except RazorpayAPIError as e:
        action_id = _persist_execution(
            case_id=case_id,
            action="SEND_PAYMENT_LINK",
            policy_decision_id=policy_decision.get("id"),
            execution_status="EXECUTION_FAILED",
            error_code=e.code,
            error_message=str(e),
            created_at=now,
            completed_at=datetime.now(IST).isoformat(),
        )
        return {
            "case_id": case_id,
            "action": "SEND_PAYMENT_LINK",
            "execution_status": "EXECUTION_FAILED",
            "policy_decision": "ALLOW",
            "policy_decision_id": policy_decision.get("id"),
            "razorpay_called": True,
            "razorpay_reference": None,
            "payment_link_id": None,
            "payment_link_url": None,
            "message": f"Razorpay API error: {e}",
            "created_at": now,
        }


def get_execution_history(case_id: str) -> list[dict]:
    """Retrieve execution history for a case."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM recovery_actions
            WHERE case_id = ?
            ORDER BY created_at DESC
            """,
            (case_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def _get_latest_policy_decision(case_id: str) -> dict | None:
    """Get the latest policy decision with its ID."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, case_id, action, decision, reason, policy_version, evaluated_at
            FROM policy_decisions
            WHERE case_id = ?
            ORDER BY evaluated_at DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def _persist_execution(
    case_id: str,
    action: str,
    policy_decision_id: int | None,
    execution_status: str,
    razorpay_reference: str | None = None,
    payment_link_id: str | None = None,
    payment_link_url: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    created_at: str = "",
    completed_at: str | None = None,
) -> int:
    """Persist an execution attempt. Returns the inserted row ID."""
    idempotency_key = f"{case_id}:{action}"
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO recovery_actions
                (case_id, action, policy_decision_id, execution_status,
                 razorpay_reference, payment_link_id, payment_link_url,
                 error_code, error_message, idempotency_key, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id, action, policy_decision_id, execution_status,
                razorpay_reference, payment_link_id, payment_link_url,
                error_code, error_message, idempotency_key, created_at, completed_at,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def _blocked_result(case_id: str, action: str, reason: str, now: str) -> dict:
    """Return a blocked execution result."""
    return {
        "case_id": case_id,
        "action": action,
        "execution_status": "BLOCKED",
        "policy_decision": "NONE",
        "policy_decision_id": None,
        "razorpay_called": False,
        "razorpay_reference": None,
        "payment_link_id": None,
        "payment_link_url": None,
        "message": reason,
        "created_at": now,
    }
