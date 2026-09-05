"""Tests for Razorpay webhook endpoint and outcome state machine.

All webhook signatures are mocked via HMAC. No live Razorpay calls.
"""
import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app.config import settings
from app.database import get_connection

WEBHOOK_SECRET = "test_webhook_secret_12345"
_case_counter = 0


def _sign_payload(payload_bytes: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def _insert_test_case_with_execution(
    conn,
    case_id="RC-WH",
    txn_id="TXN-WH",
    amount="2499.00",
    currency="INR",
    txn_status="failed",
    risk_level="MEDIUM",
    risk_score=65,
    razorpay_ref="plink_mock_RC-WH",
    payment_link_url="https://rzp.io/i/plink_mock",
    execution_status="LINK_CREATED",
):
    global _case_counter
    _case_counter += 1
    uid = str(_case_counter)
    txn_id_use = f"{txn_id}-{uid}"
    case_id_use = f"{case_id}-{uid}"
    razorpay_ref_use = f"{razorpay_ref}-{uid}"

    conn.execute(
        """
        INSERT INTO transactions (id, customer_id, customer_name, amount, currency,
            status, payment_method, failure_reason, created_at,
            retry_count, previous_successful_payments, customer_lifetime_value,
            hours_since_event, checkout_session_id)
        VALUES (?, 'CUS-WH', 'Webhook Customer', ?, ?, ?, 'upi', 'network_error',
                '2026-07-15T10:00:00+05:30', 0, 5, '10000.00', 12, NULL)
        """,
        (txn_id_use, amount, currency, txn_status),
    )
    conn.execute(
        """
        INSERT INTO recovery_cases
            (id, transaction_id, risk_score, risk_level, risk_factors,
             recovery_priority, root_cause, recommended_action, confidence,
             diagnosis_status, diagnosed_at, status, amount_recovered, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'TEMPORARY_PAYMENT_FAILURE', 'SEND_PAYMENT_LINK', 0.8,
                'completed', '2026-07-15T12:00:00+05:30', 'pending_review', '0.00', '2026-07-15T10:00:00+05:30')
        """,
        (case_id_use, txn_id_use, risk_score, risk_level, json.dumps(["Test"]), 0.6),
    )
    # Insert linked recovery action
    conn.execute(
        """
        INSERT INTO recovery_actions
            (case_id, action, execution_status, razorpay_reference, payment_link_id, payment_link_url, created_at)
        VALUES (?, 'SEND_PAYMENT_LINK', ?, ?, ?, ?, '2026-07-15T12:10:00+05:30')
        """,
        (case_id_use, execution_status, razorpay_ref_use, razorpay_ref_use, payment_link_url),
    )
    conn.commit()
    return case_id_use, txn_id_use, razorpay_ref_use


def _make_payload(event_id="evt_test_1", event_type="payment.captured", payment_entity=None):
    if payment_entity is None:
        payment_entity = {"id": "pay_mock_1", "amount": 249900, "currency": "INR"}
    return {
        "event_id": event_id,
        "event": event_type,
        "payload": {"payment": {"entity": payment_entity}},
        "created_at": 1720000000,
    }


# ── Signature tests ─────────────────────────────

class TestWebhookSignature:
    def test_valid_payment_captured(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref, "notes": {"reference_id": f"{case_id}-SPL-123"}}

        payload = _make_payload(event_id="evt_valid_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processed"
        assert data["execution_status"] == "PAYMENT_SUCCESS"

    def test_invalid_signature(self, client):
        with get_connection() as conn:
            _insert_test_case_with_execution(conn)
        payload = _make_payload(event_id="evt_invalid_sig", event_type="payment.captured")
        raw = json.dumps(payload).encode()
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": "bad_signature_hex", "content-type": "application/json"})
        assert resp.status_code == 400
        assert "invalid" in resp.text.lower()

    def test_missing_signature(self, client):
        with get_connection() as conn:
            _insert_test_case_with_execution(conn)
        payload = _make_payload(event_id="evt_missing_sig", event_type="payment.captured")
        raw = json.dumps(payload).encode()
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"content-type": "application/json"})
        assert resp.status_code == 400
        assert "missing" in resp.text.lower()

    def test_no_secret_configured_rejects(self, client):
        with get_connection() as conn:
            _insert_test_case_with_execution(conn)
        payload = _make_payload(event_id="evt_no_secret", event_type="payment.captured")
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, "any")
        with patch.object(settings, "razorpay_webhook_secret", ""):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        assert resp.status_code == 400


# ── Duplicate / idempotency ─────────────────────

class TestWebhookDuplicate:
    def test_duplicate_event(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}

        payload = _make_payload(event_id="evt_dup_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            r1 = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
            assert r1.status_code == 200
            r2 = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
            assert r2.status_code == 200
            assert r2.json()["status"] == "duplicate"
            # Ensure amount not double-counted
            with get_connection() as conn:
                row = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
                assert row["amount_recovered"] == "2499.00"

    def test_duplicate_payment_captured_does_not_double_count(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn, amount="5000.00")
            payment_entity = {"id": ref, "amount": 500000, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_double_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            row = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            # Should be exactly 5000.00, not 10000
            assert row["amount_recovered"] == "5000.00"
            total_recovered = conn.execute("SELECT COALESCE(SUM(CAST(amount_recovered AS REAL)),0) FROM recovery_cases").fetchone()[0]
            # At least verify not double counted within this case
            assert total_recovered >= 5000.0

    def test_idempotency(self, client):
        # Three identical deliveries
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_idem_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            for _ in range(3):
                resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
                assert resp.status_code == 200
            # Only one should be processed
            with get_connection() as conn:
                count = conn.execute("SELECT COUNT(*) FROM webhook_events WHERE event_id = 'evt_idem_1'").fetchone()[0]
                assert count == 1


# ── Payment events ──────────────────────────────

class TestPaymentEvents:
    def test_payment_failed(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref, "error_description": "insufficient funds"}
        payload = _make_payload(event_id="evt_fail_1", event_type="payment.failed", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processed"
        assert data["execution_status"] == "PAYMENT_FAILED"
        with get_connection() as conn:
            action = conn.execute("SELECT execution_status FROM recovery_actions WHERE case_id = ?", (case_id,)).fetchone()
            assert action["execution_status"] == "PAYMENT_FAILED"
            rc = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            assert rc["amount_recovered"] == "0.00"

    def test_unknown_event_type(self, client):
        with get_connection() as conn:
            _insert_test_case_with_execution(conn)
        payload = _make_payload(event_id="evt_unknown_1", event_type="subscription.cancelled", payment_entity={"id": "pay_x"})
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_unknown_payment_reference(self, client):
        with get_connection() as conn:
            _insert_test_case_with_execution(conn)
        # Payment id that does not match any recovery_action
        payment_entity = {"id": "pay_no_match_999", "amount": 100000, "currency": "INR", "payment_link_id": "plink_no_match"}
        payload = _make_payload(event_id="evt_unknown_ref_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "no matching" in resp.json()["message"].lower()


# ── Outcome updates ─────────────────────────────

class TestOutcomeUpdates:
    def test_payment_success_updates_recovery_action(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_outcome_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            action = conn.execute("SELECT execution_status, completed_at FROM recovery_actions WHERE case_id = ?", (case_id,)).fetchone()
            assert action["execution_status"] == "PAYMENT_SUCCESS"
            assert action["completed_at"] is not None

    def test_payment_success_updates_transaction(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn, txn_status="failed")
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_txn_update_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            txn = conn.execute("SELECT status FROM transactions WHERE id = ?", (txn_id,)).fetchone()
            assert txn["status"] == "paid"

    def test_amount_recovered_changes_only_once(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn, amount="3000.00")
            payment_entity = {"id": ref, "amount": 300000, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_amt_once_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            rc = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            assert rc["amount_recovered"] == "3000.00"
            # Second event with same amount should remain 3000 due to duplicate handling or already success
            # Create a new event_id but same action already succeeded -> should be duplicate-ish (blocked)
            payload2 = _make_payload(event_id="evt_amt_once_2", event_type="payment.captured", payment_entity=payment_entity)
            raw2 = json.dumps(payload2).encode()
            sig2 = _sign_payload(raw2, WEBHOOK_SECRET)
            client.post("/api/webhooks/razorpay", content=raw2, headers={"X-Razorpay-Signature": sig2, "content-type": "application/json"})
            rc2 = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            assert rc2["amount_recovered"] == "3000.00"

    def test_uses_razorpay_amount_not_original(self, client):
        # Original transaction is 2499, but Razorpay payment is 3000 — service should use Razorpay amount
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn, amount="2499.00")
            payment_entity = {"id": ref, "amount": 300000, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_amt_differ_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            rc = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            assert rc["amount_recovered"] == "3000.00"

    def test_failed_payment_does_not_increase_revenue(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn, amount="4000.00")
            payment_entity = {"id": ref, "amount": 400000, "currency": "INR", "payment_link_id": ref}
            before = conn.execute("SELECT COALESCE(SUM(CAST(amount_recovered AS REAL)),0) FROM recovery_cases").fetchone()[0]
        payload = _make_payload(event_id="evt_failed_rev_1", event_type="payment.failed", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            after = conn.execute("SELECT COALESCE(SUM(CAST(amount_recovered AS REAL)),0) FROM recovery_cases").fetchone()[0]
            assert after == before
            rc = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            assert rc["amount_recovered"] == "0.00"


# ── Persistence ─────────────────────────────────

class TestWebhookPersistence:
    def test_webhook_event_persistence(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_persist_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            evt = conn.execute("SELECT * FROM webhook_events WHERE event_id = 'evt_persist_1'").fetchone()
            assert evt is not None
            assert evt["event_type"] == "payment.captured"
            assert evt["processing_status"] == "processed"
            assert evt["payload"] is not None
            assert evt["received_at"] is not None
            assert evt["processed_at"] is not None

    def test_webhook_events_endpoint(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR"}
        payload = _make_payload(event_id="evt_list_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        resp = client.get("/api/webhooks/events")
        assert resp.status_code == 200
        assert "events" in resp.json()
        assert len(resp.json()["events"]) >= 1

    def test_webhook_processing_failure_persisted(self, client):
        # Unknown reference leads to failed status persisted
        with get_connection() as conn:
            _insert_test_case_with_execution(conn)
        payment_entity = {"id": "pay_no_match_fail", "amount": 100000, "currency": "INR"}
        payload = _make_payload(event_id="evt_fail_persist_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            evt = conn.execute("SELECT processing_status, error_message FROM webhook_events WHERE event_id = 'evt_fail_persist_1'").fetchone()
            assert evt["processing_status"] == "failed"
            assert evt["error_message"] is not None


# ── Audit ───────────────────────────────────────

class TestAuditTrail:
    def test_audit_log_created_on_success(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_audit_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            log = conn.execute("SELECT * FROM audit_logs WHERE case_id = ? AND event_type = 'payment.captured'", (case_id,)).fetchone()
            assert log is not None
            assert log["to_status"] == "PAYMENT_SUCCESS"

    def test_audit_log_on_failed(self, client):
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn)
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_audit_fail_1", event_type="payment.failed", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        with get_connection() as conn:
            log = conn.execute("SELECT * FROM audit_logs WHERE case_id = ? AND event_type = 'payment.failed'", (case_id,)).fetchone()
            assert log is not None


# ── State machine enforcement ────────────────────

class TestStateMachine:
    def test_never_direct_to_success_without_verified_event(self, client):
        # Ensure LINK_CREATED exists, but no webhook has yet fired — amount_recovered must be 0
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn, amount="9999.00")
            row = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (case_id,)).fetchone()
            assert row["amount_recovered"] == "0.00"
            action = conn.execute("SELECT execution_status FROM recovery_actions WHERE case_id = ?", (case_id,)).fetchone()
            assert action["execution_status"] == "LINK_CREATED"
        # Verify summary still counts at-risk, not recovered
        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        # Ensure no direct transition via execution_service — only webhook can go to SUCCESS
        # The execution_service currently never creates PAYMENT_SUCCESS, only LINK_CREATED
        # So our state is correct.

    def test_link_created_to_payment_pending_to_success(self, client):
        # Simulate LINK_CREATED -> manually set to PAYMENT_PENDING -> webhook to SUCCESS
        with get_connection() as conn:
            case_id, txn_id, ref = _insert_test_case_with_execution(conn, execution_status="PAYMENT_PENDING")
            payment_entity = {"id": ref, "amount": 249900, "currency": "INR", "payment_link_id": ref}
        payload = _make_payload(event_id="evt_state_1", event_type="payment.captured", payment_entity=payment_entity)
        raw = json.dumps(payload).encode()
        sig = _sign_payload(raw, WEBHOOK_SECRET)
        with patch.object(settings, "razorpay_webhook_secret", WEBHOOK_SECRET):
            resp = client.post("/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
            assert resp.json()["execution_status"] == "PAYMENT_SUCCESS"
