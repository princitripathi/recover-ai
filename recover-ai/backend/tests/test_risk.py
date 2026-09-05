"""Comprehensive tests for the deterministic risk scoring engine."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.services.risk_service import (
    assess_transaction,
    calculate_risk,
    risk_level_from_score,
)
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ── Risk score bounds ────────────────────────────────────────────────────

class TestRiskScoreBounds:
    """Test 1: Risk score is always between 0 and 100."""

    @pytest.mark.parametrize("status", ["paid", "failed", "abandoned", "pending"])
    def test_score_always_bounded(self, status):
        assessment = calculate_risk(
            status=status,
            amount=Decimal("99999"),
            retry_count=5,
            previous_successful_payments=20,
            customer_lifetime_value=Decimal("500000"),
            hours_since_event=720,
            failure_reason="issuer_declined",
        )
        assert 0 <= assessment.risk_score <= 100

    def test_minimal_transaction_low_score(self):
        assessment = calculate_risk(
            status="paid",
            amount=Decimal("100"),
            retry_count=5,
            previous_successful_payments=0,
            customer_lifetime_value=Decimal("0"),
            hours_since_event=720,
            failure_reason=None,
        )
        assert assessment.risk_score <= 20

    def test_maximal_risk_transaction(self):
        assessment = calculate_risk(
            status="failed",
            amount=Decimal("99999"),
            retry_count=0,
            previous_successful_payments=20,
            customer_lifetime_value=Decimal("500000"),
            hours_since_event=1,
            failure_reason="bank_downtime",
        )
        assert assessment.risk_score >= 85
        assert assessment.risk_score <= 100


# ── Risk level boundaries ────────────────────────────────────────────────

class TestRiskLevelBoundaries:
    """Test 2: HIGH/MEDIUM/LOW boundaries are correct."""

    def test_high_boundary(self):
        assert risk_level_from_score(80) == "HIGH"
        assert risk_level_from_score(100) == "HIGH"
        assert risk_level_from_score(79) == "MEDIUM"

    def test_medium_boundary(self):
        assert risk_level_from_score(50) == "MEDIUM"
        assert risk_level_from_score(79) == "MEDIUM"
        assert risk_level_from_score(49) == "LOW"

    def test_low_boundary(self):
        assert risk_level_from_score(0) == "LOW"
        assert risk_level_from_score(49) == "LOW"

    def test_level_matches_score(self):
        for score in [0, 25, 49, 50, 65, 79, 80, 90, 100]:
            level = risk_level_from_score(score)
            if score >= 80:
                assert level == "HIGH"
            elif score >= 50:
                assert level == "MEDIUM"
            else:
                assert level == "LOW"


# ── High-value transactions ──────────────────────────────────────────────

class TestHighValueRisk:
    """Test 3: High-value failed transactions receive increased risk."""

    def test_high_value_failed_beats_low_value_failed(self):
        high = calculate_risk(
            status="failed", amount=Decimal("50000"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=100, failure_reason="issuer_declined",
        )
        low = calculate_risk(
            status="failed", amount=Decimal("500"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=100, failure_reason="issuer_declined",
        )
        assert high.risk_score > low.risk_score

    def test_very_high_value_increases_significantly(self):
        base = calculate_risk(
            status="failed", amount=Decimal("1000"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=100, failure_reason="issuer_declined",
        )
        very_high = calculate_risk(
            status="failed", amount=Decimal("60000"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=100, failure_reason="issuer_declined",
        )
        assert very_high.risk_score - base.risk_score >= 10


# ── Customer history ─────────────────────────────────────────────────────

class TestCustomerHistory:
    """Test 4: Previously successful customers can increase recovery priority."""

    def test_loyal_customer_higher_priority(self):
        loyal = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=15, customer_lifetime_value=Decimal("100000"),
            hours_since_event=12, failure_reason="bank_downtime",
        )
        new_cust = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=12, failure_reason="bank_downtime",
        )
        assert loyal.recovery_priority > new_cust.recovery_priority

    def test_loyal_customer_increases_risk_score(self):
        loyal = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=10, customer_lifetime_value=Decimal("50000"),
            hours_since_event=100, failure_reason="issuer_declined",
        )
        new_cust = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=100, failure_reason="issuer_declined",
        )
        assert loyal.risk_score > new_cust.risk_score


# ── Retry count ──────────────────────────────────────────────────────────

class TestRetryCount:
    """Test 5: High retry counts reduce recovery priority."""

    def test_no_retries_higher_priority(self):
        no_retry = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=3, customer_lifetime_value=Decimal("10000"),
            hours_since_event=24, failure_reason="bank_downtime",
        )
        many_retries = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=5,
            previous_successful_payments=3, customer_lifetime_value=Decimal("10000"),
            hours_since_event=24, failure_reason="bank_downtime",
        )
        assert no_retry.recovery_priority >= many_retries.recovery_priority

    def test_no_retries_higher_priority_than_many(self):
        no_retry = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=3, customer_lifetime_value=Decimal("10000"),
            hours_since_event=24, failure_reason="bank_downtime",
        )
        many_retries = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=5,
            previous_successful_payments=3, customer_lifetime_value=Decimal("10000"),
            hours_since_event=24, failure_reason="bank_downtime",
        )
        assert no_retry.recovery_priority > many_retries.recovery_priority


# ── Recency ──────────────────────────────────────────────────────────────

class TestRecency:
    """Test 6: Older events are appropriately deprioritized."""

    def test_recent_higher_priority(self):
        recent = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=3, customer_lifetime_value=Decimal("10000"),
            hours_since_event=2, failure_reason="bank_downtime",
        )
        old = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=3, customer_lifetime_value=Decimal("10000"),
            hours_since_event=500, failure_reason="bank_downtime",
        )
        assert recent.recovery_priority > old.recovery_priority
        assert recent.risk_score > old.risk_score

    def test_very_old_events_low_recency_score(self):
        very_old = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=720, failure_reason="issuer_declined",
        )
        brand_new = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=0, customer_lifetime_value=Decimal("0"),
            hours_since_event=1, failure_reason="issuer_declined",
        )
        assert brand_new.risk_score > very_old.risk_score


# ── Risk factors ─────────────────────────────────────────────────────────

class TestRiskFactors:
    """Test 7: Risk factors are generated."""

    def test_factors_always_generated(self):
        assessment = calculate_risk(
            status="failed", amount=Decimal("5000"), retry_count=0,
            previous_successful_payments=3, customer_lifetime_value=Decimal("10000"),
            hours_since_event=24, failure_reason="bank_downtime",
        )
        assert isinstance(assessment.risk_factors, list)
        assert len(assessment.risk_factors) >= 4

    def test_factors_are_strings(self):
        assessment = calculate_risk(
            status="abandoned", amount=Decimal("2000"), retry_count=2,
            previous_successful_payments=1, customer_lifetime_value=Decimal("5000"),
            hours_since_event=100, failure_reason="checkout_timeout",
        )
        for factor in assessment.risk_factors:
            assert isinstance(factor, str)
            assert len(factor) > 0

    def test_paid_transaction_has_factors(self):
        assessment = calculate_risk(
            status="paid", amount=Decimal("1000"), retry_count=0,
            previous_successful_payments=5, customer_lifetime_value=Decimal("20000"),
            hours_since_event=24, failure_reason=None,
        )
        assert len(assessment.risk_factors) >= 3


# ── Determinism ──────────────────────────────────────────────────────────

class TestDeterminism:
    """Test 8: Risk scoring is deterministic."""

    def test_same_inputs_same_output(self):
        args = dict(
            status="failed", amount=Decimal("12345.67"), retry_count=2,
            previous_successful_payments=7, customer_lifetime_value=Decimal("45000"),
            hours_since_event=48, failure_reason="insufficient_funds",
        )
        a = calculate_risk(**args)
        b = calculate_risk(**args)
        assert a.risk_score == b.risk_score
        assert a.risk_level == b.risk_level
        assert a.recovery_priority == b.recovery_priority
        assert a.risk_factors == b.risk_factors

    def test_deterministic_across_many_calls(self):
        results = set()
        for _ in range(50):
            a = calculate_risk(
                status="failed", amount=Decimal("8000"), retry_count=1,
                previous_successful_payments=3, customer_lifetime_value=Decimal("15000"),
                hours_since_event=36, failure_reason="network_error",
            )
            results.add(a.risk_score)
        assert len(results) == 1


# ── Only failed/abandoned ────────────────────────────────────────────────

class TestRecoveryCaseCreation:
    """Test 9: Only failed/abandoned transactions create recovery-risk cases."""

    def test_failed_creates_case(self, client):
        resp = client.get("/api/risk/cases")
        assert resp.status_code == 200
        cases = resp.json()
        assert len(cases) > 0
        for case in cases:
            assert case["transaction_status"] in {"failed", "abandoned"}

    def test_no_paid_in_risk_cases(self, client):
        resp = client.get("/api/risk/cases")
        cases = resp.json()
        statuses = {c["transaction_status"] for c in cases}
        assert "paid" not in statuses
        assert "pending" not in statuses


# ── Risk summary ─────────────────────────────────────────────────────────

class TestRiskSummary:
    """Test 10: Risk summary values match database values."""

    def test_summary_totals_add_up(self, client):
        resp = client.get("/api/risk/summary")
        assert resp.status_code == 200
        s = resp.json()
        assert s["high_risk_cases"] + s["medium_risk_cases"] + s["low_risk_cases"] == s["total_risk_cases"]

    def test_summary_revenue_consistency(self, client):
        resp = client.get("/api/risk/summary")
        s = resp.json()
        high = Decimal(str(s["high_risk_revenue"]))
        med = Decimal(str(s["medium_risk_revenue"]))
        low = Decimal(str(s["low_risk_revenue"]))
        total = Decimal(str(s["revenue_at_risk"]))
        assert high + med + low == total

    def test_summary_non_empty(self, client):
        s = client.get("/api/risk/summary").json()
        assert s["total_risk_cases"] > 0
        assert Decimal(str(s["revenue_at_risk"])) > 0


# ── Risk API filters ─────────────────────────────────────────────────────

class TestRiskAPIFilters:
    """Test 11: Risk API filters work."""

    def test_filter_high(self, client):
        resp = client.get("/api/risk/cases?risk_level=HIGH")
        assert resp.status_code == 200
        for case in resp.json():
            assert case["risk_level"] == "HIGH"

    def test_filter_medium(self, client):
        resp = client.get("/api/risk/cases?risk_level=MEDIUM")
        assert resp.status_code == 200
        for case in resp.json():
            assert case["risk_level"] == "MEDIUM"

    def test_filter_low(self, client):
        resp = client.get("/api/risk/cases?risk_level=LOW")
        assert resp.status_code == 200
        for case in resp.json():
            assert case["risk_level"] == "LOW"

    def test_invalid_sort_by(self, client):
        resp = client.get("/api/risk/cases?sort_by=invalid_field")
        assert resp.status_code == 400

    def test_invalid_order(self, client):
        resp = client.get("/api/risk/cases?order=up")
        assert resp.status_code == 400

    def test_sort_by_risk_score_desc(self, client):
        resp = client.get("/api/risk/cases?sort_by=risk_score&order=desc")
        cases = resp.json()
        scores = [c["risk_score"] for c in cases]
        assert scores == sorted(scores, reverse=True)

    def test_sort_by_risk_score_asc(self, client):
        resp = client.get("/api/risk/cases?sort_by=risk_score&order=asc")
        cases = resp.json()
        scores = [c["risk_score"] for c in cases]
        assert scores == sorted(scores)

    def test_get_single_case(self, client):
        all_cases = client.get("/api/risk/cases").json()
        case_id = all_cases[0]["id"]
        resp = client.get(f"/api/risk/cases/{case_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == case_id
        assert "risk_factors" in resp.json()

    def test_get_nonexistent_case(self, client):
        resp = client.get("/api/risk/cases/RC-NONEXISTENT")
        assert resp.status_code == 404


# ── Stage 1 backward compatibility ───────────────────────────────────────

class TestBackwardCompatibility:
    """Test 12: Existing Stage 1 endpoints still work with new schema."""

    def test_transactions_still_work(self, client):
        resp = client.get("/api/transactions")
        assert resp.status_code == 200
        txns = resp.json()
        assert len(txns) >= 500
        first = txns[0]
        assert "retry_count" in first
        assert "previous_successful_payments" in first
        assert "customer_lifetime_value" in first
        assert "hours_since_event" in first
        assert "checkout_session_id" in first

    def test_dashboard_still_works(self, client):
        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        s = resp.json()
        assert s["total_transactions"] >= 500

    def test_recovery_cases_still_work(self, client):
        resp = client.get("/api/recovery-cases")
        assert resp.status_code == 200
        assert len(resp.json()) > 0

    def test_health_still_works(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_new_transaction_fields_present(self, client):
        resp = client.get("/api/transactions")
        txn = resp.json()[0]
        assert "retry_count" in txn
        assert isinstance(txn["retry_count"], int)
        assert "previous_successful_payments" in txn
        assert isinstance(txn["previous_successful_payments"], int)

    def test_recovery_cases_have_risk_fields(self, client):
        resp = client.get("/api/recovery-cases")
        case = resp.json()[0]
        assert "risk_level" in case
        assert case["risk_level"] in {"HIGH", "MEDIUM", "LOW"}
        assert "risk_factors" in case
        assert "recovery_priority" in case
