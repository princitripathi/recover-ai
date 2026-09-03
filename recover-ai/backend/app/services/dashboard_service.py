from decimal import Decimal
from app.database import get_connection


class DashboardService:
    def get_summary(self):
        with get_connection() as conn:
            total_transactions = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            revenue_processed = conn.execute(
                "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) FROM transactions WHERE status = 'paid'"
            ).fetchone()[0]
            revenue_at_risk = conn.execute(
                "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) FROM transactions WHERE status IN ('failed', 'abandoned')"
            ).fetchone()[0]
            failed_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE status = 'failed'").fetchone()[0]
            abandoned_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE status = 'abandoned'").fetchone()[0]
            recovery_cases = conn.execute("SELECT COUNT(*) FROM recovery_cases").fetchone()[0]
            revenue_recovered = conn.execute(
                "SELECT COALESCE(SUM(CAST(amount_recovered AS REAL)), 0) FROM recovery_cases"
            ).fetchone()[0]
            cases_to_review = conn.execute("SELECT COUNT(*) FROM recovery_cases WHERE status = 'open'").fetchone()[0]

        risk = Decimal(str(revenue_at_risk)).quantize(Decimal("0.01"))
        recovered = Decimal(str(revenue_recovered)).quantize(Decimal("0.01"))
        recovery_rate = float((recovered / risk * Decimal("100")).quantize(Decimal("0.01"))) if risk else 0.0
        return {
            "total_transactions": total_transactions,
            "revenue_processed": Decimal(str(revenue_processed)).quantize(Decimal("0.01")),
            "revenue_at_risk": risk,
            "failed_transaction_count": failed_count,
            "abandoned_transaction_count": abandoned_count,
            "recovery_cases": recovery_cases,
            "revenue_recovered": recovered,
            "recovery_rate": recovery_rate,
            "cases_to_review": cases_to_review,
        }
