"""Tests for the deterministic policy engine.

All tests mock the database directly — no Ollama, no Razorpay dependency.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app.config import settings
from app.database import get_connection, init_db
from app.services.policy_service import evaluate_policy, get_policy_decision

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
    recommended_action="RETRY_PAYMENT",
    confidence=0.8,
    case_status="pending_review",
):
    """Insert a test transaction + recovery case. Returns the case_id used."""
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
        VALUES (?, 'CUS-TEST', 'Test Customer', ?, 'INR', ?, 'upi', 'temporary_failure',
                '2026-07-15T10:00:00+05:30', ?, 5, '10000.00', 48, NULL)
        """,
        (txn_id_use, amount, txn_status, retry_count),
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


# ── RETRY_PAYMENT ALLOW ──────────────────────────────────────────────

class TestRetryPaymentAllow:
    def test_retry_payment_allowed(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.8)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"
        assert data["action"] == "RETRY_PAYMENT"
        assert data["case_id"] == cid
        assert len(data["rules_evaluated"]) == 6
        assert data["policy_version"] == "1.0.0"
        assert data["evaluated_at"] is not None

    def test_retry_payment_allowed_low_confidence_at_threshold(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.6)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"


# ── RETRY_PAYMENT BLOCK ──────────────────────────────────────────────

class TestRetryPaymentBlock:
    def test_retry_blocked_retry_count_exceeded(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", retry_count=3, confidence=0.8)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "retry" in data["reason"].lower()

    def test_retry_blocked_high_risk(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", risk_level="HIGH", risk_score=85, confidence=0.8)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "high" in data["reason"].lower()

    def test_retry_blocked_amount_exceeds_limit(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", amount="30000.00", confidence=0.8)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "amount" in data["reason"].lower()

    def test_retry_blocked_low_confidence(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.41)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "confidence" in data["reason"].lower()

    def test_retry_blocked_abandoned_status(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", txn_status="abandoned", confidence=0.8)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "failed" in data["reason"].lower()


# ── SEND_PAYMENT_LINK ────────────────────────────────────────────────

class TestSendPaymentLink:
    def test_send_payment_link_allowed_abandoned(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK", txn_status="abandoned")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"
        assert data["action"] == "SEND_PAYMENT_LINK"

    def test_send_payment_link_allowed_failed(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK", txn_status="failed")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"

    def test_send_payment_link_blocked_high_risk(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK", risk_level="HIGH", risk_score=90)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "high" in data["reason"].lower()

    def test_send_payment_link_blocked_amount_exceeds_limit(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK", amount="60000.00")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "amount" in data["reason"].lower()

    def test_send_payment_link_blocked_paid_status(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="SEND_PAYMENT_LINK", txn_status="paid")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"


# ── CONTACT_CUSTOMER ─────────────────────────────────────────────────

class TestContactCustomer:
    def test_contact_customer_allowed_failed(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="CONTACT_CUSTOMER", txn_status="failed")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"
        assert data["action"] == "CONTACT_CUSTOMER"

    def test_contact_customer_allowed_abandoned(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="CONTACT_CUSTOMER", txn_status="abandoned")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"

    def test_contact_customer_blocked_paid(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="CONTACT_CUSTOMER", txn_status="paid")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"


# ── ESCALATE ─────────────────────────────────────────────────────────

class TestEscalate:
    def test_escalate_always_allowed(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="ESCALATE", risk_level="HIGH", risk_score=95, confidence=0.2)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"
        assert data["action"] == "ESCALATE"
        assert len(data["rules_evaluated"]) == 1
        assert data["rules_evaluated"][0]["rule"] == "escalate_always_allowed"

    def test_escalate_allowed_regardless_of_risk(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="ESCALATE", risk_level="HIGH", risk_score=100, confidence=0.1)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"


# ── NO_ACTION ────────────────────────────────────────────────────────

class TestNoAction:
    def test_no_action_always_allowed(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="NO_ACTION")
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"
        assert data["action"] == "NO_ACTION"
        assert len(data["rules_evaluated"]) == 1
        assert data["rules_evaluated"][0]["rule"] == "no_action_always_allowed"


# ── MISSING / UNAVAILABLE ───────────────────────────────────────────

class TestMissingDiagnosis:
    def test_missing_diagnosis_blocks(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, diagnosis_status="pending", recommended_action=None)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"
        assert "diagnosis" in data["reason"].lower()

    def test_ai_unavailable_blocks(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, diagnosis_status="ai_unavailable", recommended_action=None)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"

    def test_parse_error_blocks(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, diagnosis_status="parse_error", recommended_action=None)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"


class TestUnknownCase:
    def test_unknown_case_returns_404(self, client):
        resp = client.post("/api/recovery-cases/RC-NONEXISTENT/policy-check")
        assert resp.status_code == 404

    def test_unknown_case_get_policy_returns_404(self, client):
        resp = client.get("/api/recovery-cases/RC-NONEXISTENT/policy")
        assert resp.status_code == 404


# ── PERSISTENCE ──────────────────────────────────────────────────────

class TestPolicyPersistence:
    def test_policy_decision_persisted(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.8)
        client.post(f"/api/recovery-cases/{cid}/policy-check")
        resp = client.get(f"/api/recovery-cases/{cid}/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == cid
        assert data["action"] == "RETRY_PAYMENT"
        assert data["decision"] in ("ALLOW", "BLOCK")
        assert data["reason"] is not None
        assert data["policy_version"] == "1.0.0"

    def test_policy_decision_retrievable_after_block(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.3)
        client.post(f"/api/recovery-cases/{cid}/policy-check")
        resp = client.get(f"/api/recovery-cases/{cid}/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BLOCK"

    def test_get_policy_before_check_returns_404(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn)
        resp = client.get(f"/api/recovery-cases/{cid}/policy")
        assert resp.status_code == 404


# ── DETERMINISM ──────────────────────────────────────────────────────

class TestPolicyDeterminism:
    def test_same_inputs_same_output(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.8)
        r1 = client.post(f"/api/recovery-cases/{cid}/policy-check").json()
        with get_connection() as conn:
            conn.execute("DELETE FROM policy_decisions")
            conn.commit()
        r2 = client.post(f"/api/recovery-cases/{cid}/policy-check").json()
        assert r1["decision"] == r2["decision"]
        assert r1["action"] == r2["action"]
        assert r1["reason"] == r2["reason"]

    def test_deterministic_across_multiple_calls(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.8)
        results = []
        for _ in range(5):
            with get_connection() as conn:
                conn.execute("DELETE FROM policy_decisions")
                conn.commit()
            resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
            results.append(resp.json()["decision"])
        assert len(set(results)) == 1


# ── SAFETY: NO LLM, NO RAZORPAY ─────────────────────────────────────

class TestPolicySafety:
    def test_policy_never_calls_ollama(self, client):
        """Verify the policy engine has no Ollama dependency."""
        from app.services import policy_service
        assert not hasattr(policy_service, '_call_ollama')

    def test_policy_never_calls_razorpay(self, client):
        """Verify the policy engine has no Razorpay API calls."""
        from app.services import policy_service
        import inspect
        source = inspect.getsource(policy_service)
        assert "import razorpay" not in source.lower()
        assert "razorpay.Client" not in source
        assert "razorpay.api" not in source


# ── RULES EVALUATED STRUCTURE ───────────────────────────────────────

class TestRulesEvaluated:
    def test_retry_payment_has_six_rules(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.8)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        data = resp.json()
        assert len(data["rules_evaluated"]) == 6
        rule_names = [r["rule"] for r in data["rules_evaluated"]]
        assert "transaction_status_failed" in rule_names
        assert "retry_count_below_threshold" in rule_names
        assert "risk_level_not_high" in rule_names
        assert "amount_within_limit" in rule_names
        assert "ai_confidence_above_threshold" in rule_names
        assert "case_eligible" in rule_names

    def test_rules_have_required_fields(self, client):
        with get_connection() as conn:
            cid = _insert_test_case(conn, recommended_action="RETRY_PAYMENT", confidence=0.8)
        resp = client.post(f"/api/recovery-cases/{cid}/policy-check")
        data = resp.json()
        for rule in data["rules_evaluated"]:
            assert "rule" in rule
            assert "passed" in rule
            assert "detail" in rule
            assert isinstance(rule["passed"], bool)


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
