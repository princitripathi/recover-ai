"""Webhook service for RecoverAI — Razorpay signature verification, idempotency, outcome state machine.

Uses official Razorpay webhook signature mechanism: HMAC SHA256 of raw body with secret.
Never trusts an unverified webhook. Persists every event. Idempotent via event_id uniqueness.
Only verified payment success updates amount_recovered.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.config import settings
from app.database import get_connection

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SUPPORTED_EVENTS = {"payment.captured", "payment.failed"}
VALID_TRANSITIONS = {
    "LINK_CREATED": {"PAYMENT_SUCCESS", "PAYMENT_FAILED", "PAYMENT_PENDING"},
    "PAYMENT_PENDING": {"PAYMENT_SUCCESS", "PAYMENT_FAILED"},
}


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Razorpay webhook signature using HMAC SHA256.

    Official Razorpay mechanism: hex digest of HMAC-SHA256(payload, secret)
    compared with the value in X-Razorpay-Signature header.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    # Razorpay may send signature as hex; compare securely
    return hmac.compare_digest(expected, signature)


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _persist_event(
    event_id: str,
    event_type: str,
    payload_json: str,
    processing_status: str,
    razorpay_reference: str | None = None,
    error_message: str | None = None,
) -> None:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO webhook_events
                (event_id, event_type, payload, processing_status, received_at, processed_at, error_message, razorpay_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                payload_json,
                processing_status,
                now,
                now if processing_status in ("processed", "failed", "ignored", "duplicate") else None,
                error_message,
                razorpay_reference,
            ),
        )
        # If row already exists but status needs update for duplicate handling, do it elsewhere
        conn.commit()


def _update_event_status(event_id: str, status: str, error_message: str | None = None) -> None:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE webhook_events SET processing_status = ?, processed_at = ?, error_message = ? WHERE event_id = ?",
            (status, now, error_message, event_id),
        )
        conn.commit()


def _find_recovery_action(razorpay_payment_entity: dict) -> dict | None:
    """Find corresponding recovery_action for a Razorpay payment entity.

    Tries multiple referencing strategies:
    - entity.id == recovery_actions.razorpay_reference or payment_link_id
    - entity.payment_link_id == recovery_actions.payment_link_id or razorpay_reference
    - entity.notes.reference_id or entity.reference_id or entity.order_id
    Returns the most relevant action row (LINK_CREATED / PAYMENT_PENDING preferred).
    """
    payment_id = razorpay_payment_entity.get("id")
    payment_link_id = razorpay_payment_entity.get("payment_link_id") or razorpay_payment_entity.get("payment_link") or ""
    notes = razorpay_payment_entity.get("notes") or {}
    reference_id = notes.get("reference_id") or razorpay_payment_entity.get("reference_id") or razorpay_payment_entity.get("order_id") or ""

    candidates = [v for v in [payment_id, payment_link_id, reference_id] if v]

    with get_connection() as conn:
        for ref in candidates:
            # Try exact matches on razorpay_reference and payment_link_id
            row = conn.execute(
                """
                SELECT ra.*, rc.transaction_id FROM recovery_actions ra
                JOIN recovery_cases rc ON rc.id = ra.case_id
                WHERE ra.razorpay_reference = ? OR ra.payment_link_id = ?
                ORDER BY ra.created_at DESC LIMIT 1
                """,
                (ref, ref),
            ).fetchone()
            if row is not None:
                return dict(row)

        # Fallback: try LIKE match for reference_id containing case id (e.g., "RC-xxx-SPL-...")
        # Search for case_id pattern inside reference_id
        if reference_id:
            # reference_id often is "RC-<caseId>-SPL-<timestamp>"; extract case id
            # Try to find RC- number from reference
            import re
            # reference contains case_id like RC-xxx
            matches = re.findall(r"RC-[A-Za-z0-9\-_]+", reference_id)
            for m in matches:
                # Try to match case prefix
                row = conn.execute(
                    """
                    SELECT ra.*, rc.transaction_id FROM recovery_actions ra
                    JOIN recovery_cases rc ON rc.id = ra.case_id
                    WHERE ra.case_id LIKE ? OR rc.id LIKE ?
                    ORDER BY ra.created_at DESC LIMIT 1
                    """,
                    (f"%{m}%", f"%{m}%"),
                ).fetchone()
                if row is not None:
                    return dict(row)

    # Last attempt: broad LIKE on any candidate substring in razorpay_reference
    with get_connection() as conn:
        for ref in candidates:
            row = conn.execute(
                """
                SELECT ra.*, rc.transaction_id FROM recovery_actions ra
                JOIN recovery_cases rc ON rc.id = ra.case_id
                WHERE ra.razorpay_reference LIKE ? OR ra.payment_link_id LIKE ?
                ORDER BY ra.created_at DESC LIMIT 1
                """,
                (f"%{ref[:8]}%", f"%{ref[:8]}%"),
            ).fetchone()
            if row is not None:
                # Require at least prefix match to avoid false positives with short ids
                if len(ref) >= 6:
                    return dict(row)
    return None


def _create_audit_log(case_id: str | None, transaction_id: str | None, event_type: str, from_status: str | None, to_status: str | None, amount: str | None, details: str | None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (case_id, transaction_id, event_type, from_status, to_status, amount, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (case_id, transaction_id, event_type, from_status, to_status, amount, details, _now_iso()),
        )
        conn.commit()


def process_webhook_event(
    raw_body: bytes,
    headers: dict,
    payload_dict: dict | None = None,
) -> dict:
    """Process a webhook event with signature verification and idempotency.

    Callers should pass raw_body and headers (containing x-razorpay-signature).
    payload_dict may be provided to avoid double parsing; if None it is parsed from raw_body.

    Returns a dict with status info for HTTP response.
    Raises ValueError for missing/invalid signature so route can return 400.
    """
    # --- Signature presence check ---
    signature = headers.get("x-razorpay-signature") or headers.get("X-Razorpay-Signature") or headers.get("x_razorpay_signature")
    if not signature:
        # Try case-insensitive lookup
        for k, v in headers.items():
            if k.lower() == "x-razorpay-signature":
                signature = v
                break

    if not signature:
        raise ValueError("Missing Razorpay signature")

    secret = settings.razorpay_webhook_secret
    # If no secret configured, we cannot verify — reject unless in test without secret? For tests, allow empty secret to bypass? But spec says Do NOT trust unverified.
    # For tests, they set RECOVERAI_RAZORPAY_WEBHOOK_SECRET and we verify against that.
    # If secret is empty, treat as invalid signature (require secret)
    if not secret:
        raise ValueError("Invalid signature: webhook secret not configured")

    if not verify_signature(raw_body, str(signature), secret):
        raise ValueError("Invalid Razorpay signature")

    # Parse payload if not given
    if payload_dict is None:
        try:
            payload_dict = json.loads(raw_body.decode() if isinstance(raw_body, (bytes, bytearray)) else str(raw_body))
        except Exception as e:
            raise ValueError(f"Invalid JSON payload: {e}")

    # Extract event fields (Razorpay sends {event, payload} or flat? Handle both)
    # Common shape: {"entity": "event", "account_id": "...", "event": "payment.captured", "contains": ["payment"], "payload": {"payment": {"entity": {...}}}, "created_at": 123}
    # Also synthetic shape for tests: {"event_id": "evt_xxx", "event": "payment.captured", "payload": {...}}
    event_type = payload_dict.get("event") or payload_dict.get("event_type") or payload_dict.get("type") or ""
    event_id = payload_dict.get("event_id") or payload_dict.get("id") or payload_dict.get("entity_id") or ""
    # Razorpay often uses payload.payment.entity.id as not top-level id. Use entity field for event_id fallback.
    if not event_id:
        event_id = str(payload_dict.get("created_at") or payload_dict.get("timestamp") or "") + "_" + event_type
        # Ensure uniqueness: hash body if still empty-like
        if event_id.startswith("_") or not event_id.strip("_"):
            event_id = "evt_" + hashlib.sha256(raw_body).hexdigest()[:16]

    # Idempotency: check if event_id already processed
    with get_connection() as conn:
        existing = conn.execute("SELECT * FROM webhook_events WHERE event_id = ?", (event_id,)).fetchone()

    if existing is not None:
        existing_status = existing["processing_status"]
        # Return successful idempotent response — do not reprocess
        return {
            "status": "duplicate",
            "event_id": event_id,
            "event_type": event_type,
            "message": f"Duplicate event {event_id} already processed (status={existing_status})",
            "existing_status": existing_status,
        }

    # Persist as received first
    payload_str = json.dumps(payload_dict)
    # Determine razorpay reference for storage
    razorpay_ref_preview = ""
    try:
        if "payload" in payload_dict and isinstance(payload_dict["payload"], dict):
            # Try to extract payment id for preview
            pay = payload_dict["payload"].get("payment", {})
            if isinstance(pay, dict):
                ent = pay.get("entity", {})
                if isinstance(ent, dict):
                    razorpay_ref_preview = ent.get("id", "") or ent.get("payment_link_id", "")
    except Exception:
        pass

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO webhook_events (event_id, event_type, payload, processing_status, received_at, razorpay_reference)
            VALUES (?, ?, ?, 'received', ?, ?)
            """,
            (event_id, event_type, payload_str, _now_iso(), razorpay_ref_preview),
        )
        conn.commit()

    # Handle unknown event types gracefully — ignore but mark as processed
    if event_type not in SUPPORTED_EVENTS:
        _update_event_status(event_id, "ignored", f"Unknown event type: {event_type}")
        _create_audit_log(None, None, event_type, None, None, None, f"Ignored unknown event {event_id} type={event_type}")
        return {
            "status": "ignored",
            "event_id": event_id,
            "event_type": event_type,
            "message": f"Event type {event_type} ignored",
        }

    # Extract payment entity
    payment_entity: dict | None = None
    # Shape 1: {"payload": {"payment": {"entity": {...}}}}
    if "payload" in payload_dict and isinstance(payload_dict["payload"], dict):
        pay_wrap = payload_dict["payload"].get("payment", {})
        if isinstance(pay_wrap, dict):
            if "entity" in pay_wrap and isinstance(pay_wrap["entity"], dict):
                payment_entity = pay_wrap["entity"]
            elif isinstance(pay_wrap, dict) and "id" in pay_wrap:
                payment_entity = pay_wrap
        # Also shape {"payload": {"payment_link": ...}} not supported for capture
    # Shape 2: {"payload": {"payment": {...}}} direct
    # Shape 3: {"payment": {"entity": {...}}}
    if payment_entity is None and "payment" in payload_dict:
        pw = payload_dict["payment"]
        if isinstance(pw, dict):
            payment_entity = pw.get("entity") if "entity" in pw else pw

    # Shape 4: legacy synthetic: {"payload": {"payment": {"id": ..., "amount": ...}}}
    if payment_entity is None:
        # try top-level entity field
        if "entity" in payload_dict and isinstance(payload_dict["entity"], dict):
            payment_entity = payload_dict["entity"]

    if payment_entity is None or not isinstance(payment_entity, dict):
        _update_event_status(event_id, "failed", "Unable to extract payment entity from payload")
        return {
            "status": "failed",
            "event_id": event_id,
            "event_type": event_type,
            "message": "Unable to extract payment entity",
        }

    # Find corresponding recovery action
    action = _find_recovery_action(payment_entity)
    if action is None:
        _update_event_status(event_id, "failed", f"No matching recovery action found for reference payment_id={payment_entity.get('id')} link_id={payment_entity.get('payment_link_id')}")
        _create_audit_log(None, None, event_type, None, None, None, f"No matching recovery action for event {event_id} reference={payment_entity.get('id')}")
        return {
            "status": "failed",
            "event_id": event_id,
            "event_type": event_type,
            "message": "No matching recovery action found for webhook reference",
            "razorpay_reference": payment_entity.get("id"),
        }

    case_id = action["case_id"]
    action_id = action["id"]
    from_status = action["execution_status"]
    transaction_id = action.get("transaction_id")

    # Validate transition
    if from_status == "PAYMENT_SUCCESS":
        # Already succeeded — idempotent amount protection, do not double-count
        _update_event_status(event_id, "duplicate", f"Recovery action {action_id} already PAYMENT_SUCCESS, idempotent skip")
        return {
            "status": "duplicate",
            "event_id": event_id,
            "event_type": event_type,
            "message": "Action already marked PAYMENT_SUCCESS, no double counting",
            "case_id": case_id,
        }

    # Determine target status and amount logic
    now = _now_iso()
    if event_type == "payment.captured":
        target_status = "PAYMENT_SUCCESS"
        # Verify allowed transition
        if from_status not in ("LINK_CREATED", "PAYMENT_PENDING"):
            # Unexpected state — block direct transition if not in valid source
            # But spec says Never transition directly to PAYMENT_SUCCESS without verified event — this IS verified, so allow if action exists?
            # If action is BLOCKED or EXECUTION_FAILED, do not transition to SUCCESS
            if from_status in ("BLOCKED", "EXECUTION_FAILED", "PAYMENT_FAILED"):
                _update_event_status(event_id, "failed", f"Invalid transition {from_status} -> {target_status}")
                return {
                    "status": "failed",
                    "event_id": event_id,
                    "event_type": event_type,
                    "message": f"Cannot transition from {from_status} to {target_status}",
                    "case_id": case_id,
                }
        # Calculate amount from Razorpay entity (amount is in paise)
        # Razorpay amount is integer paise; convert to Decimal rupees
        try:
            raw_amount = payment_entity.get("amount")
            if raw_amount is not None:
                # Razorpay paise -> rupees
                recovered = (Decimal(str(raw_amount)) / Decimal("100")).quantize(Decimal("0.01"))
            else:
                # Fallback to notes amount or original transaction amount
                amt_str = str(action.get("amount") or "0")  # not available in action dict; fetch transaction
                # Fetch actual transaction amount if we need fallback
                with get_connection() as conn:
                    txn_row = conn.execute("SELECT amount FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
                    amt_str = txn_row["amount"] if txn_row else "0.00"
                recovered = Decimal(amt_str).quantize(Decimal("0.01"))
        except Exception as e:
            logger.error("Amount conversion failed: %s", e)
            _update_event_status(event_id, "failed", f"Amount conversion failed: {e}")
            return {"status": "failed", "event_id": event_id, "event_type": event_type, "message": f"Amount conversion failed: {e}"}

        # Update recovery action, transaction, and recovery case
        with get_connection() as conn:
            # Update recovery action status
            conn.execute(
                "UPDATE recovery_actions SET execution_status = ?, completed_at = ?, razorpay_reference = COALESCE(razorpay_reference, ?) WHERE id = ?",
                (target_status, now, payment_entity.get("id"), action_id),
            )
            # Update recovery case amount_recovered ONLY if not already set (prevent double count)
            # Check existing amount_recovered
            rc_row = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            existing_recovered = Decimal(str(rc_row["amount_recovered"])) if rc_row else Decimal("0.00")
            if existing_recovered == Decimal("0.00") or from_status != "PAYMENT_SUCCESS":
                # Only increase if not already recovered
                conn.execute(
                    "UPDATE recovery_cases SET amount_recovered = ?, status = 'recovered' WHERE id = ?",
                    (str(recovered), case_id),
                )
                amount_to_report = recovered
            else:
                # Already recovered — do not double count
                amount_to_report = existing_recovered

            # Mark transaction as paid (captured) where appropriate — only if not already paid
            # We keep original failure reason for audit but flip status to paid so revenue_at_risk decrements
            txn_row2 = conn.execute("SELECT status FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
            if txn_row2 and txn_row2["status"] in ("failed", "abandoned", "pending"):
                conn.execute("UPDATE transactions SET status = 'paid' WHERE id = ?", (transaction_id,))

            conn.commit()

        _update_event_status(event_id, "processed", None)
        _create_audit_log(case_id, transaction_id, event_type, from_status, target_status, str(recovered), f"Payment captured verified for event {event_id}, payment_id={payment_entity.get('id')}, amount={recovered}")
        return {
            "status": "processed",
            "event_id": event_id,
            "event_type": event_type,
            "case_id": case_id,
            "action_id": action_id,
            "execution_status": target_status,
            "amount_recovered": str(recovered),
            "message": "Payment captured processed, amount_recovered updated",
        }

    elif event_type == "payment.failed":
        target_status = "PAYMENT_FAILED"
        # Validate transition — allow from LINK_CREATED / PAYMENT_PENDING
        if from_status in ("PAYMENT_SUCCESS",):
            _update_event_status(event_id, "duplicate", "Already succeeded, failure ignored")
            return {"status": "duplicate", "event_id": event_id, "event_type": event_type, "message": "Already PAYMENT_SUCCESS"}

        now = _now_iso()
        with get_connection() as conn:
            conn.execute(
                "UPDATE recovery_actions SET execution_status = ?, completed_at = ?, error_message = COALESCE(error_message, ?) WHERE id = ?",
                (target_status, now, f"Payment failed via webhook {event_id}", action_id),
            )
            # Do NOT increase amount_recovered
            conn.commit()

        _update_event_status(event_id, "processed", None)
        failure_reason = payment_entity.get("error_description") or payment_entity.get("failure_reason") or "payment_failed"
        _create_audit_log(case_id, transaction_id, event_type, from_status, target_status, None, f"Payment failed verified for event {event_id}, payment_id={payment_entity.get('id')}, reason={failure_reason}")
        return {
            "status": "processed",
            "event_id": event_id,
            "event_type": event_type,
            "case_id": case_id,
            "action_id": action_id,
            "execution_status": target_status,
            "message": "Payment failure processed, amount_recovered unchanged",
        }

    # Default fallback
    _update_event_status(event_id, "failed", "Unhandled event type branch")
    return {"status": "failed", "event_id": event_id, "event_type": event_type, "message": "Unhandled event type"}
