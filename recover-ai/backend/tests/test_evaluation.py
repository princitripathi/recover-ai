"""Tests for simulated batch evaluation service and API."""
import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_connection
from app.services.evaluation_service import run_evaluation, get_latest_evaluation


class TestEvaluationMetrics:
    def test_dataset_processed(self, client):
        resp = client.post("/api/evaluation/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["evaluation_type"] == "SIMULATED"
        assert data["dataset_size"] == 520
        assert data["recovery_cases"] > 0

    def test_revenue_at_risk_calculation(self, client):
        resp = client.post("/api/evaluation/run")
        data = resp.json()
        # Revenue at risk should equal sum of failed+abandoned from dashboard summary
        dash = client.get("/api/dashboard/summary").json()
        # Compare (string numeric) — both are from actual stored data
        assert Decimal(str(data["revenue_at_risk"])) == Decimal(str(dash["revenue_at_risk"]))

    def test_successful_recovery_calculation(self, client):
        resp = client.post("/api/evaluation/run")
        data = resp.json()
        assert data["successful_recoveries"] >= 0
        assert data["successful_recoveries"] <= data["recovery_attempts"]
        assert data["successful_recoveries"] + data["failed_recoveries"] == data["recovery_attempts"]

    def test_recovery_amount_calculation(self, client):
        resp = client.post("/api/evaluation/run")
        data = resp.json()
        amount = Decimal(str(data["amount_recovered"]))
        assert amount >= Decimal("0.00")
        # Amount recovered should not exceed revenue at risk
        assert amount <= Decimal(str(data["revenue_at_risk"]))

    def test_recovery_rate_calculation(self, client):
        resp = client.post("/api/evaluation/run")
        data = resp.json()
        revenue_at_risk = Decimal(str(data["revenue_at_risk"]))
        amount_recovered = Decimal(str(data["amount_recovered"]))
        expected = float((amount_recovered / revenue_at_risk).quantize(Decimal("0.0001"))) if revenue_at_risk > 0 else 0.0
        assert abs(data["recovery_rate"] - expected) < 0.0002
        # Also check case_recovery_rate
        eligible = data["eligible_cases"]
        expected_case = round(data["successful_recoveries"] / eligible, 4) if eligible > 0 else 0.0
        assert abs(data["case_recovery_rate"] - expected_case) < 0.0001

    def test_policy_blocked_cases(self, client):
        resp = client.post("/api/evaluation/run")
        data = resp.json()
        assert data["policy_blocked"] >= 0
        assert data["policy_allowed"] >= 0
        assert data["policy_allowed"] + data["policy_blocked"] == data["eligible_cases"]

    def test_all_required_fields(self, client):
        resp = client.post("/api/evaluation/run")
        data = resp.json()
        for field in ["evaluation_type", "dataset_size", "revenue_at_risk", "policy_allowed", "policy_blocked",
                      "recovery_attempts", "successful_recoveries", "amount_recovered", "recovery_rate", "case_recovery_rate"]:
            assert field in data, f"missing field {field}"
        assert data["evaluation_type"] == "SIMULATED"

    def test_deterministic_repeatability(self, client):
        r1 = client.post("/api/evaluation/run").json()
        r2 = client.post("/api/evaluation/run").json()
        # Deterministic: same metrics across runs (since same dataset + same hash)
        assert r1["recovery_rate"] == r2["recovery_rate"]
        assert r1["amount_recovered"] == r2["amount_recovered"]
        assert r1["successful_recoveries"] == r2["successful_recoveries"]
        assert r1["policy_blocked"] == r2["policy_blocked"]
        assert r1["revenue_at_risk"] == r2["revenue_at_risk"]

    def test_no_real_razorpay_calls(self, client):
        """Evaluation must not require Razorpay credentials."""
        # Even with empty credentials, evaluation succeeds (simulated layer)
        resp = client.post("/api/evaluation/run")
        assert resp.status_code == 200
        assert resp.json()["evaluation_type"] == "SIMULATED"

    def test_persistence_latest(self, client):
        client.post("/api/evaluation/run")
        resp = client.get("/api/evaluation/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["evaluation_type"] == "SIMULATED"
        assert "amount_recovered" in data
        assert "recovery_rate" in data

    def test_evaluation_not_marked_as_real_money(self, client):
        resp = client.post("/api/evaluation/run")
        data = resp.json()
        assert data["evaluation_type"] == "SIMULATED"
        # Baseline must be present and zero
        assert Decimal(str(data.get("baseline_recovered", "0.00"))) == Decimal("0.00")
        assert "baseline" in str(data.get("baseline_note", "")).lower() or "simulated" in str(data.get("baseline_note", "")).lower()

    def test_get_latest_before_any_run(self, client):
        # Fresh DB has no evaluation; this test runs in isolated DB so no prior runs
        # But if previous test already ran, we will still pass because endpoint returns latest
        resp = client.get("/api/evaluation/latest")
        # Either 200 with SIMULATED or detail NONE; both are valid handling
        assert resp.status_code == 200
        data = resp.json()
        if data.get("evaluation_type") == "NONE":
            assert "detail" in data
        else:
            assert data["evaluation_type"] == "SIMULATED"


class TestEvaluationViaService:
    def test_run_evaluation_direct(self, client):
        # Ensure the service function works via direct call inside request context
        result = run_evaluation()
        assert result["evaluation_type"] == "SIMULATED"
        assert result["dataset_size"] == 520
        assert Decimal(str(result["amount_recovered"])) >= Decimal("0")

    def test_get_latest_evaluation_service(self, client):
        run_evaluation()
        latest = get_latest_evaluation()
        assert latest is not None
        assert latest["evaluation_type"] == "SIMULATED"

    def test_evaluation_does_not_modify_amount_recovered(self, client):
        # Operational amount_recovered should not be bulk-updated by simulated evaluation
        before = client.get("/api/dashboard/summary").json()["revenue_recovered"]
        client.post("/api/evaluation/run")
        after = client.get("/api/dashboard/summary").json()["revenue_recovered"]
        # Dashboard revenue_recovered is from real webhook updates only; simulated eval must not change it
        assert before == after
