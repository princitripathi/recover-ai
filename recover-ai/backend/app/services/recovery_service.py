from decimal import Decimal
from app.database import get_connection


class RecoveryService:
    def list_cases(self):
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT rc.*, t.customer_name, t.amount, t.currency, t.status AS transaction_status,
                       t.failure_reason, t.retry_count, t.previous_successful_payments,
                       t.customer_lifetime_value, t.hours_since_event
                FROM recovery_cases rc
                JOIN transactions t ON t.id = rc.transaction_id
                ORDER BY rc.risk_score DESC, rc.created_at DESC
                """
            ).fetchall()
        cases = []
        for row in rows:
            data = dict(row)
            data["amount"] = Decimal(data["amount"])
            data["amount_recovered"] = Decimal(data["amount_recovered"])
            data["customer_lifetime_value"] = Decimal(data["customer_lifetime_value"])
            cases.append(data)
        return cases
