"""Comprehensive tests for AI diagnosis service.

All tests mock the LLM provider — no live Ollama required.
"""
import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.diagnosis import (
    DiagnosisResult,
    VALID_ACTIONS,
    VALID_ROOT_CAUSES,
)
from app.services.diagnosis_service import (
    _parse_llm_response,
    diagnose_case,
    get_diagnosis,
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_llm_response():
    return json.dumps({
        "root_cause": "TEMPORARY_PAYMENT_FAILURE",
        "recommended_action": "RETRY_PAYMENT",
        "confidence": 0.85,
        "reason": "The transaction failed due to bank downtime, which is a temporary issue. Retrying payment is likely to succeed.",
        "risk_factors": ["Failed transaction", "Temporary-looking failure: bank_downtime", "Loyal customer"],
    })


@pytest.fixture
def first_case_id(client):
    """Get the first recovery case ID from the test database."""
    resp = client.get("/api/recovery-cases")
    cases = resp.json()
    return cases[0]["id"]


def _mock_call_ollama(response_text):
    """Create a mock for _call_ollama that returns the given text."""
    return patch("app.services.diagnosis_service._call_ollama", return_value=response_text)


def _mock_call_ollama_error(error_msg="Connection refused"):
    """Create a mock for _call_ollama that raises an exception."""
    return patch("app.services.diagnosis_service._call_ollama", side_effect=Exception(error_msg))


# ── Test 1: Successful AI diagnosis ──────────────────────────────────────

class TestSuccessfulDiagnosis:
    def test_diagnose_returns_completed(self, client, first_case_id, sample_llm_response):
        with _mock_call_ollama(sample_llm_response):
            resp = client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diagnosis_status"] == "completed"
        assert data["case_id"] == first_case_id
        assert data["root_cause"] == "TEMPORARY_PAYMENT_FAILURE"
        assert data["recommended_action"] == "RETRY_PAYMENT"
        assert data["confidence"] == 0.85
        assert "reason" in data
        assert isinstance(data["risk_factors"], list)

    def test_diagnosis_persists_to_database(self, client, first_case_id, sample_llm_response):
        with _mock_call_ollama(sample_llm_response):
            client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        resp = client.get(f"/api/recovery-cases/{first_case_id}/diagnosis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diagnosis_status"] == "completed"
        assert data["root_cause"] == "TEMPORARY_PAYMENT_FAILURE"

    def test_retrieve_stored_diagnosis(self, client, first_case_id, sample_llm_response):
        with _mock_call_ollama(sample_llm_response):
            client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        resp = client.get(f"/api/recovery-cases/{first_case_id}/diagnosis")
        assert resp.status_code == 200
        assert resp.json()["case_id"] == first_case_id


# ── Test 2: Structured response validation ───────────────────────────────

class TestStructuredResponseValidation:
    def test_valid_diagnosis_result(self):
        result = DiagnosisResult(
            root_cause="BANK_DECLINE",
            recommended_action="CONTACT_CUSTOMER",
            confidence=0.72,
            reason="The bank declined the transaction.",
            risk_factors=["Bank failure"],
        )
        assert result.root_cause in VALID_ROOT_CAUSES
        assert result.recommended_action in VALID_ACTIONS
        assert 0.0 <= result.confidence <= 1.0

    def test_parse_valid_json(self, sample_llm_response):
        result = _parse_llm_response(sample_llm_response)
        assert isinstance(result, DiagnosisResult)
        assert result.root_cause in VALID_ROOT_CAUSES
        assert result.recommended_action in VALID_ACTIONS
        assert 0.0 <= result.confidence <= 1.0

    def test_parse_markdown_code_block(self):
        raw = '```json\n{"root_cause": "INSUFFICIENT_FUNDS", "recommended_action": "SEND_PAYMENT_LINK", "confidence": 0.6, "reason": "Low funds.", "risk_factors": ["f1"]}\n```'
        result = _parse_llm_response(raw)
        assert result.root_cause == "INSUFFICIENT_FUNDS"
        assert result.recommended_action == "SEND_PAYMENT_LINK"

    def test_parse_plain_code_block(self):
        raw = '```\n{"root_cause": "CUSTOMER_ABANDONMENT", "recommended_action": "CONTACT_CUSTOMER", "confidence": 0.5, "reason": "Customer left.", "risk_factors": []}\n```'
        result = _parse_llm_response(raw)
        assert result.root_cause == "CUSTOMER_ABANDONMENT"


# ── Test 3: Invalid AI response ──────────────────────────────────────────

class TestInvalidAIResponse:
    def test_invalid_json_returns_defaults(self):
        result = _parse_llm_response("this is not json at all")
        assert result.root_cause == "UNKNOWN_FAILURE"
        assert result.recommended_action == "NO_ACTION"
        assert result.confidence == 0.5

    def test_invalid_root_cause_falls_back(self):
        raw = json.dumps({
            "root_cause": "TOTALLY_INVALID",
            "recommended_action": "RETRY_PAYMENT",
            "confidence": 0.5,
            "reason": "test",
            "risk_factors": [],
        })
        result = _parse_llm_response(raw)
        assert result.root_cause == "UNKNOWN_FAILURE"

    def test_invalid_action_falls_back(self):
        raw = json.dumps({
            "root_cause": "BANK_DECLINE",
            "recommended_action": "DO_SOMETHING_WILD",
            "confidence": 0.5,
            "reason": "test",
            "risk_factors": [],
        })
        result = _parse_llm_response(raw)
        assert result.recommended_action == "NO_ACTION"


# ── Test 4: AI unavailable ───────────────────────────────────────────────

class TestAIUnavailable:
    def test_ai_unavailable_returns_status(self, client, first_case_id):
        with _mock_call_ollama_error("Connection refused"):
            resp = client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diagnosis_status"] == "ai_unavailable"
        assert "error" in data

    def test_ai_unavailable_persists_status(self, client, first_case_id):
        with _mock_call_ollama_error("timeout"):
            client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        resp = client.get(f"/api/risk/cases/{first_case_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diagnosis_status"] == "ai_unavailable"

    def test_ai_unavailable_does_not_crash(self, client, first_case_id):
        with _mock_call_ollama_error("Service down"):
            resp = client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        assert resp.status_code == 200
        # Verify the API is still functional
        health = client.get("/api/health")
        assert health.status_code == 200


# ── Test 5: Unknown recovery case ────────────────────────────────────────

class TestUnknownCase:
    def test_unknown_case_returns_404(self, client):
        resp = client.post("/api/recovery-cases/RC-NONEXISTENT/diagnose")
        assert resp.status_code == 404

    def test_unknown_case_diagnosis_returns_404(self, client):
        resp = client.get("/api/recovery-cases/RC-NONEXISTENT/diagnosis")
        assert resp.status_code == 404

    def test_diagnose_case_function_returns_error(self, client):
        result = diagnose_case("RC-NONEXISTENT")
        assert result["diagnosis_status"] == "error"
        assert "not found" in result.get("error", "").lower()


# ── Test 6: Confidence validation ────────────────────────────────────────

class TestConfidenceValidation:
    def test_confidence_clamped_above_1(self):
        raw = json.dumps({
            "root_cause": "BANK_DECLINE",
            "recommended_action": "RETRY_PAYMENT",
            "confidence": 5.0,
            "reason": "test",
            "risk_factors": [],
        })
        result = _parse_llm_response(raw)
        assert result.confidence == 1.0

    def test_confidence_clamped_below_0(self):
        raw = json.dumps({
            "root_cause": "BANK_DECLINE",
            "recommended_action": "RETRY_PAYMENT",
            "confidence": -2.0,
            "reason": "test",
            "risk_factors": [],
        })
        result = _parse_llm_response(raw)
        assert result.confidence == 0.0

    def test_confidence_valid_range(self):
        for val in [0.0, 0.25, 0.5, 0.75, 1.0]:
            raw = json.dumps({
                "root_cause": "BANK_DECLINE",
                "recommended_action": "RETRY_PAYMENT",
                "confidence": val,
                "reason": "test",
                "risk_factors": [],
            })
            result = _parse_llm_response(raw)
            assert result.confidence == val

    def test_missing_confidence_defaults(self):
        raw = json.dumps({
            "root_cause": "BANK_DECLINE",
            "recommended_action": "RETRY_PAYMENT",
            "reason": "test",
            "risk_factors": [],
        })
        result = _parse_llm_response(raw)
        assert result.confidence == 0.5


# ── Test 7: Invalid recommended action ───────────────────────────────────

class TestInvalidAction:
    def test_unknown_action_becomes_no_action(self):
        raw = json.dumps({
            "root_cause": "BANK_DECLINE",
            "recommended_action": "TRANSFER_MONEY_NOW",
            "confidence": 0.8,
            "reason": "test",
            "risk_factors": [],
        })
        result = _parse_llm_response(raw)
        assert result.recommended_action == "NO_ACTION"

    def test_valid_actions_accepted(self):
        for action in VALID_ACTIONS:
            raw = json.dumps({
                "root_cause": "BANK_DECLINE",
                "recommended_action": action,
                "confidence": 0.5,
                "reason": "test",
                "risk_factors": [],
            })
            result = _parse_llm_response(raw)
            assert result.recommended_action == action

    def test_valid_root_causes_accepted(self):
        for rc in VALID_ROOT_CAUSES:
            raw = json.dumps({
                "root_cause": rc,
                "recommended_action": "NO_ACTION",
                "confidence": 0.5,
                "reason": "test",
                "risk_factors": [],
            })
            result = _parse_llm_response(raw)
            assert result.root_cause == rc


# ── Test 8: Diagnosis does NOT execute financial action ──────────────────

class TestNoFinancialExecution:
    def test_diagnosis_only_returns_data(self, client, first_case_id, sample_llm_response):
        """Diagnosis must only return structured data, never trigger payments."""
        with _mock_call_ollama(sample_llm_response):
            resp = client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        data = resp.json()
        # The response should contain recommendation, not execution
        assert data["diagnosis_status"] == "completed"
        assert "root_cause" in data
        assert "recommended_action" in data
        # There should be no payment execution fields
        assert "payment_executed" not in data
        assert "razorpay_id" not in data
        assert "transaction_completed" not in data

    def test_diagnosis_does_not_change_amount_recovered(self, client, first_case_id, sample_llm_response):
        """amount_recovered must remain 0 after diagnosis."""
        before = client.get(f"/api/risk/cases/{first_case_id}").json()
        with _mock_call_ollama(sample_llm_response):
            client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        after = client.get(f"/api/risk/cases/{first_case_id}").json()
        assert before["amount_recovered"] == after["amount_recovered"] == "0.00"

    def test_diagnosis_preserves_existing_status(self, client, first_case_id, sample_llm_response):
        """Recovery case status should not change to 'recovered'."""
        with _mock_call_ollama(sample_llm_response):
            client.post(f"/api/recovery-cases/{first_case_id}/diagnose")
        case = client.get(f"/api/risk/cases/{first_case_id}").json()
        assert case["status"] == "pending_review"


# ── Test 9: Pydantic validation ──────────────────────────────────────────

class TestPydanticValidation:
    def test_diagnosis_result_validation(self):
        with pytest.raises(Exception):
            DiagnosisResult(
                root_cause="INVALID",
                recommended_action="RETRY_PAYMENT",
                confidence=2.0,  # Out of range
                reason="test",
                risk_factors=[],
            )

    def test_confidence_must_be_numeric(self):
        with pytest.raises(Exception):
            DiagnosisResult(
                root_cause="BANK_DECLINE",
                recommended_action="RETRY_PAYMENT",
                confidence="not_a_number",
                reason="test",
                risk_factors=[],
            )


# ── Test 10: Backward compatibility ──────────────────────────────────────

class TestBackwardCompatDiagnosis:
    def test_all_endpoints_still_work(self, client):
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/transactions").status_code == 200
        assert client.get("/api/recovery-cases").status_code == 200
        assert client.get("/api/dashboard/summary").status_code == 200
        assert client.get("/api/risk/cases").status_code == 200
        assert client.get("/api/risk/summary").status_code == 200

    def test_pending_diagnosis_status_default(self, client, first_case_id):
        """New cases should have diagnosis_status='pending'."""
        resp = client.get(f"/api/risk/cases/{first_case_id}")
        assert resp.status_code == 200
        assert resp.json()["diagnosis_status"] == "pending"
