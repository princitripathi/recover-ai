from decimal import Decimal
from fastapi import HTTPException
from app.database import get_connection

AT_RISK_STATUSES = {"failed", "abandoned"}


def _transaction_from_row(row):
    data = dict(row)
    data["amount"] = Decimal(data["amount"])
    data["is_revenue_at_risk"] = data["status"] in AT_RISK_STATUSES
    return data


class TransactionService:
    def list_transactions(self):
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM transactions ORDER BY created_at DESC").fetchall()
        return [_transaction_from_row(row) for row in rows]

    def get_transaction(self, transaction_id: str):
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return _transaction_from_row(row)
