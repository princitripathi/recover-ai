"""Tests for the execution service and Razorpay integration.

All Razorpay calls are mocked. No live credentials needed.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app.config import settings
from app.database import get_connection
from app.services.execution_service import execute_recovery_action, get_execution_history
from app.services.razorpay_service import has_credentials, RazorpayAPIError

_case_counter = 0


def _insert_test_case(
    conn,
    case_id="RC-TEST",
    txn_id="TXN-TEST",
    txn_status="failed",
    amount="5000.00",
    retry_count=0,
    risk_level="MEDIUM",
    risk_score=65,
    risk_factors=None,
    recovery_priority=0.5,
    diagnosis_status="completed",
    root_cause="TEMPORARY_PAYMENT_FAILURE",
    recommended_action="SEND_PAYMENT_LINK",
    confidence=0.8,
    case_status="pending_review",
    customer_name="Test Customer",
):
    """Insert a test transaction + recovery case. Returns (case_id, txn_id) used."""
    global _case_counter
    _case_counter += 1
    uid = str(_case_counter)
    txn_id_use = f"{txn_id}-{uid}"
    case_id_use = f"{case_id}-{uid}"

    if risk_factors is None:
        risk_factors = ["Test factor"]
    conn.execute(
        """
        INSERT OR REPLACE INTO transactions (id, customer_id, customer_name, amount, currency,
            status, payment_method, failure_reason, created_at,
            retry_count, previous_successful_payments, customer_lifetime_value,
            hours_since_event, checkout_session_id)
        VALUES (?, 'CUS-TEST', ?, ?, 'INR', ?, 'upi', 'temporary_failure',
                '2026-07-15T10:00:00+05:30', ?, 5, '10000.00', 48, NULL)
        """,
        (txn_id_use, customer_name, amount, txn_status, retry_count),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO recovery_cases
            (id, transaction_id, risk_score, risk_level, risk_factors,
             recovery_priority, root_cause, recommended_action, confidence,
             diagnosis_status, diagnosed_at, status, amount_recovered, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-07-15T12:00:00+05:30', ?, '0.00', '2026-07-15T10:00:00+05:30')
        """,
        (case_id_use, txn_id_use, risk_score, risk_level, json.dumps(risk_factors),
         recovery_priority, root_cause, recommended_action, confidence,
         diagnosis_status, case_status),
    )
    conn.commit()
    return case_id_use


def _insert_policy_decision(conn, case_id, action="SEND_PAYMENT_LINK", decision="ALLOW"):
    """Insert a policy decision. Returns the decision ID."""
    conn.execute(
        """
        INSERT INTO policy_decisions (case_id, action, decision, reason, rules_evaluated, policy_version, evaluated_at)
        VALUES (?, ?, ?, ?, ?, '1.0.0', '2026-07-15T12:05:00+05:30')
        """,
        (case_id, action, decision, f"Policy {decision}: test", json.dumps([])),
    )
    conn.commit()
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


def _mock_razorpay_success(amount_paise=500000, currency="INR", reference_id="RC-TEST"):
    """Return a mock Razorpay success response."""
    return {
        "id": f"plink_mock_{reference_id}",
        "short_url": f"https://rzp.io/i/{reference_id}",
        "status": "created",
        "amount": amount_paise,
        "currency": currency,
        "reference_id": reference_id,
        "customer": {"name": "Test Customer"},
    }


# ── SUCCESSFUL PAYMENT LINK CREATION ────────────────────────────────

class TestSuccessfulExecution:
    def test_successful_payment_link_creation(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_status"] == "LINK_CREATED"
        assert data["razorpay_called"] is True
        assert data["razorpay_reference"] is not None
        assert data["payment_link_url"] is not None
        assert data["payment_link_url"].startswith("https://")
        assert data["policy_decision"] == "ALLOW"
        assert data["case_id"] == cid
        assert data["action"] == "SEND_PAYMENT_LINK"

    def test_execution_persists_to_database(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        resp = client.get(f"/api/recovery-cases/{cid}/actions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["actions"]) == 1
        assert data["actions"][0]["execution_status"] == "LINK_CREATED"
        assert data["actions"][0]["razorpay_reference"] is not None


# ── POLICY GATE ──────────────────────────────────────────────────────

class TestPolicyGate:
    def test_policy_allow_razorpay_called(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        data = resp.json()
        assert data["razorpay_called"] is True

    def test_policy_block_razorpay_not_called(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "BLOCK")

        with patch("app.services.execution_service.create_payment_link") as mock_rp:
            resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})
            mock_rp.assert_not_called()

        data = resp.json()
        assert data["execution_status"] == "BLOCKED"
        assert data["razorpay_called"] is False
        assert "BLOCK" in data["policy_decision"]

    def test_missing_policy_razorpay_not_called(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")

        with patch("app.services.execution_service.create_payment_link") as mock_rp:
            resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})
            mock_rp.assert_not_called()

        data = resp.json()
        assert data["execution_status"] == "BLOCKED"
        assert data["razorpay_called"] is False

    def test_action_mismatch_razorpay_not_called(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "RETRY_PAYMENT", "ALLOW")

        with patch("app.services.execution_service.create_payment_link") as mock_rp:
            resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})
            mock_rp.assert_not_called()

        data = resp.json()
        assert data["execution_status"] == "BLOCKED"
        assert data["razorpay_called"] is False
        assert "mismatch" in data["message"].lower()


# ── CREDENTIALS ──────────────────────────────────────────────────────

class TestCredentials:
    def test_missing_credentials_returns_execution_failed(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        with patch("app.services.execution_service.has_credentials", return_value=False):
            resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        data = resp.json()
        assert data["execution_status"] == "EXECUTION_FAILED"
        assert data["razorpay_called"] is False
        assert "credentials" in data["message"].lower()

    def test_has_credentials_false_when_empty(self):
        with patch.object(settings, "razorpay_key_id", ""), \
             patch.object(settings, "razorpay_key_secret", ""):
            assert has_credentials() is False

    def test_has_credentials_true_when_set(self):
        with patch.object(settings, "razorpay_key_id", "rzp_test_xxx"), \
             patch.object(settings, "razorpay_key_secret", "secret123"):
            assert has_credentials() is True


# ── RAZORPAY API FAILURE ─────────────────────────────────────────────

class TestRazorpayFailure:
    def test_razorpay_api_failure(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        with patch("app.services.execution_service.create_payment_link", side_effect=RazorpayAPIError("Authentication failed", code="BAD_AUTH")):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        data = resp.json()
        assert data["execution_status"] == "EXECUTION_FAILED"
        assert data["razorpay_called"] is True
        assert "Authentication failed" in data["message"]

    def test_razorpay_timeout(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        with patch("app.services.execution_service.create_payment_link", side_effect=RazorpayAPIError("Razorpay API timeout: Connection timed out")):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        data = resp.json()
        assert data["execution_status"] == "EXECUTION_FAILED"
        assert "timeout" in data["message"].lower()

    def test_razorpay_invalid_amount(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        with patch("app.services.execution_service.create_payment_link", side_effect=RazorpayAPIError("Amount must be at least 100", code="BAD_REQUEST", status_code=400)):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        data = resp.json()
        assert data["execution_status"] == "EXECUTION_FAILED"


# ── DUPLICATE EXECUTION PROTECTION ───────────────────────────────────

class TestDuplicateExecution:
    def test_duplicate_execution_blocked(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                # First execution
                resp1 = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})
                assert resp1.json()["execution_status"] == "LINK_CREATED"

                # Duplicate execution
                resp2 = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})
                data2 = resp2.json()
                assert data2["execution_status"] == "BLOCKED"
                assert "duplicate" in data2["message"].lower()

    def test_failed_execution_allows_retry(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        with patch("app.services.execution_service.create_payment_link", side_effect=RazorpayAPIError("Temporary failure")):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp1 = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})
                assert resp1.json()["execution_status"] == "EXECUTION_FAILED"

        # Retry should work since previous was not successful
        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp2 = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})
                assert resp2.json()["execution_status"] == "LINK_CREATED"


# ── AUDIT TRAIL ──────────────────────────────────────────────────────

class TestAuditTrail:
    def test_execution_history_persisted(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        resp = client.get(f"/api/recovery-cases/{cid}/actions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == cid
        assert len(data["actions"]) == 1
        action = data["actions"][0]
        assert action["case_id"] == cid
        assert action["action"] == "SEND_PAYMENT_LINK"
        assert action["execution_status"] == "LINK_CREATED"
        assert action["razorpay_reference"] is not None
        assert action["created_at"] is not None

    def test_multiple_executions_recorded(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        # First: success
        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        # Record the first action's ID and manually change status to allow retry
        with get_connection() as conn:
            conn.execute("UPDATE recovery_actions SET execution_status = 'PAYMENT_FAILED' WHERE case_id = ?", (cid,))
            conn.commit()

        # Second: also success (new link)
        mock_response2 = _mock_razorpay_success(reference_id=f"{cid}-v2")
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response2):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        resp = client.get(f"/api/recovery-cases/{cid}/actions")
        data = resp.json()
        assert len(data["actions"]) == 2


# ── SECRETS NEVER IN RESPONSES ───────────────────────────────────────

class TestSecretsNeverExposed:
    def test_credentials_not_in_response(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        response_text = resp.text
        assert "rzp_test" not in response_text.lower()
        assert "secret" not in response_text.lower()
        assert "key_id" not in response_text.lower()

    def test_error_messages_no_credentials(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        with patch("app.services.execution_service.has_credentials", return_value=False):
            resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        response_text = resp.text
        assert "key_secret" not in response_text.lower()


# ── AMOUNT NOT RECOVERED ─────────────────────────────────────────────

class TestAmountNotRecovered:
    def test_payment_link_does_not_increase_recovered(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK", amount="10000.00")
            _insert_policy_decision(conn, cid, "SEND_PAYMENT_LINK", "ALLOW")

        # Check initial amount_recovered
        with get_connection() as conn:
            row = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (cid,)).fetchone()
            initial_recovered = row[0]

        mock_response = _mock_razorpay_success(reference_id=cid)
        with patch("app.services.execution_service.create_payment_link", return_value=mock_response):
            with patch("app.services.execution_service.has_credentials", return_value=True):
                client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "SEND_PAYMENT_LINK"})

        # Verify amount_recovered unchanged
        with get_connection() as conn:
            row = conn.execute("SELECT amount_recovered FROM recovery_cases WHERE id = ?", (cid,)).fetchone()
            assert row[0] == initial_recovered


# ── UNKNOWN CASE ─────────────────────────────────────────────────────

class TestUnknownCase:
    def test_unknown_case_returns_blocked(self, client):
        resp = client.post("/api/recovery-cases/RC-NONEXISTENT/execute", json={"action": "SEND_PAYMENT_LINK"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_status"] == "BLOCKED"
        assert "not found" in data["message"].lower()

    def test_unknown_case_actions_returns_empty(self, client):
        resp = client.get("/api/recovery-cases/RC-NONEXISTENT/actions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["actions"] == []


# ── UNSUPPORTED ACTION ───────────────────────────────────────────────

class TestUnsupportedAction:
    def test_retry_payment_not_supported_yet(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT")
            _insert_policy_decision(conn, cid, "RETRY_PAYMENT", "ALLOW")

        with patch("app.services.execution_service.has_credentials", return_value=True):
            resp = client.post(f"/api/recovery-cases/{cid}/execute", json={"action": "RETRY_PAYMENT"})
            data = resp.json()
            assert data["execution_status"] == "EXECUTION_FAILED"
            assert "not supported" in data["message"].lower()


# ── BACKWARD COMPATIBILITY ──────────────────────────────────────────

class TestBackwardCompatibility:
    def test_all_endpoints_still_work(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        resp = client.get("/api/transactions")
        assert resp.status_code == 200
        resp = client.get("/api/recovery-cases")
        assert resp.status_code == 200
        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        resp = client.get("/api/risk/cases")
        assert resp.status_code == 200
        resp = client.get("/api/risk/summary")
        assert resp.status_code == 200
