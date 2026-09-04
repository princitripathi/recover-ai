import csv
import sqlite3
from decimal import Decimal
from pathlib import Path
from app.config import settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('paid', 'failed', 'abandoned', 'pending')),
    payment_method TEXT NOT NULL,
    failure_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recovery_cases (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE,
    risk_score INTEGER NOT NULL CHECK (risk_score >= 0 AND risk_score <= 100),
    root_cause TEXT,
    recommended_action TEXT,
    confidence REAL,
    status TEXT NOT NULL,
    amount_recovered TEXT NOT NULL DEFAULT '0.00',
    created_at TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
);
"""


def get_connection() -> sqlite3.Connection:
    db_path = settings.sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        if conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0:
            seed_demo_data(conn)


def seed_demo_data(conn: sqlite3.Connection) -> None:
    data_path = Path(settings.demo_data_path)
    if not data_path.is_absolute():
        data_path = Path(__file__).resolve().parents[1] / data_path
    with data_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    for row in rows:
        conn.execute(
            """
            INSERT INTO transactions (id, customer_id, customer_name, amount, currency, status, payment_method, failure_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"], row["customer_id"], row["customer_name"], row["amount"], row["currency"],
                row["status"], row["payment_method"], row["failure_reason"] or None, row["created_at"],
            ),
        )
        if row["status"] in {"failed", "abandoned"}:
            risk_score = 86 if row["status"] == "failed" else 72
            if Decimal(row["amount"]) >= Decimal("10000"):
                risk_score = min(risk_score + 8, 95)
            conn.execute(
                """
                INSERT INTO recovery_cases (id, transaction_id, risk_score, root_cause, recommended_action, confidence, status, amount_recovered, created_at)
                VALUES (?, ?, ?, NULL, NULL, NULL, 'open', '0.00', ?)
                """,
                (f"RC-{row['id'].split('-')[-1]}", row["id"], risk_score, row["created_at"]),
            )
    conn.commit()
