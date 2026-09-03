from decimal import Decimal


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_transaction_retrieval(client):
    response = client.get("/api/transactions")
    assert response.status_code == 200
    transactions = response.json()
    assert len(transactions) >= 12
    assert {item["status"] for item in transactions} >= {"paid", "failed", "abandoned", "pending"}

    detail = client.get(f"/api/transactions/{transactions[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == transactions[0]["id"]


def test_dashboard_summary(client):
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_transactions"] >= 12
    assert summary["failed_transaction_count"] > 0
    assert summary["abandoned_transaction_count"] > 0
    assert summary["recovery_cases"] == summary["failed_transaction_count"] + summary["abandoned_transaction_count"]


def test_revenue_at_risk_calculation(client):
    transactions = client.get("/api/transactions").json()
    expected = sum(Decimal(item["amount"]) for item in transactions if item["status"] in {"failed", "abandoned"})
    summary = client.get("/api/dashboard/summary").json()
    assert Decimal(summary["revenue_at_risk"]) == expected.quantize(Decimal("0.01"))
