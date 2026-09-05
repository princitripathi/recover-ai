import csv
import json
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
    created_at TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    previous_successful_payments INTEGER NOT NULL DEFAULT 0,
    customer_lifetime_value TEXT NOT NULL DEFAULT '0.00',
    hours_since_event INTEGER NOT NULL DEFAULT 0,
    checkout_session_id TEXT
);

CREATE TABLE IF NOT EXISTS recovery_cases (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE,
    risk_score INTEGER NOT NULL CHECK (risk_score >= 0 AND risk_score <= 100),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('HIGH', 'MEDIUM', 'LOW')),
    risk_factors TEXT NOT NULL DEFAULT '[]',
    recovery_priority REAL NOT NULL DEFAULT 0.0,
    root_cause TEXT,
    recommended_action TEXT,
    confidence REAL,
    diagnosis_reason TEXT,
    diagnosis_status TEXT NOT NULL DEFAULT 'pending',
    diagnosed_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    amount_recovered TEXT NOT NULL DEFAULT '0.00',
    created_at TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    action TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('ALLOW', 'BLOCK')),
    reason TEXT NOT NULL,
    rules_evaluated TEXT NOT NULL DEFAULT '[]',
    policy_version TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES recovery_cases(id)
);

CREATE TABLE IF NOT EXISTS recovery_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    action TEXT NOT NULL,
    policy_decision_id INTEGER,
    execution_status TEXT NOT NULL CHECK (execution_status IN (
        'BLOCKED', 'LINK_CREATED', 'PAYMENT_PENDING', 'PAYMENT_SUCCESS',
        'PAYMENT_FAILED', 'EXECUTION_FAILED'
    )),
    razorpay_reference TEXT,
    payment_link_url TEXT,
    payment_link_id TEXT,
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (case_id) REFERENCES recovery_cases(id),
    FOREIGN KEY (policy_decision_id) REFERENCES policy_decisions(id)
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    processing_status TEXT NOT NULL CHECK (processing_status IN ('received', 'processed', 'failed', 'duplicate', 'ignored')),
    received_at TEXT NOT NULL,
    processed_at TEXT,
    error_message TEXT,
    razorpay_reference TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_type TEXT NOT NULL DEFAULT 'SIMULATED',
    dataset_size INTEGER NOT NULL,
    total_transactions INTEGER NOT NULL,
    total_revenue TEXT NOT NULL,
    revenue_at_risk TEXT NOT NULL,
    recovery_cases INTEGER NOT NULL,
    eligible_cases INTEGER NOT NULL,
    policy_allowed INTEGER NOT NULL,
    policy_blocked INTEGER NOT NULL,
    recovery_attempts INTEGER NOT NULL,
    successful_recoveries INTEGER NOT NULL,
    failed_recoveries INTEGER NOT NULL,
    amount_recovered TEXT NOT NULL,
    recovery_rate REAL NOT NULL,
    case_recovery_rate REAL NOT NULL,
    baseline_recovered TEXT NOT NULL DEFAULT '0.00',
    baseline_note TEXT NOT NULL DEFAULT 'No automated recovery (simulated baseline)',
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    transaction_id TEXT,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    amount TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);
"""

MIGRATION_ADDITIONS = """
ALTER TABLE transactions ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN previous_successful_payments INTEGER NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN customer_lifetime_value TEXT NOT NULL DEFAULT '0.00';
ALTER TABLE transactions ADD COLUMN hours_since_event INTEGER NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN checkout_session_id TEXT;
ALTER TABLE recovery_cases ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'MEDIUM';
ALTER TABLE recovery_cases ADD COLUMN risk_factors TEXT NOT NULL DEFAULT '[]';
ALTER TABLE recovery_cases ADD COLUMN recovery_priority REAL NOT NULL DEFAULT 0.0;
"""


def get_connection() -> sqlite3.Connection:
    db_path = settings.sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0:
            seed_demo_data(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    migrations = [
        ("transactions", "retry_count", "ALTER TABLE transactions ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"),
        ("transactions", "previous_successful_payments", "ALTER TABLE transactions ADD COLUMN previous_successful_payments INTEGER NOT NULL DEFAULT 0"),
        ("transactions", "customer_lifetime_value", "ALTER TABLE transactions ADD COLUMN customer_lifetime_value TEXT NOT NULL DEFAULT '0.00'"),
        ("transactions", "hours_since_event", "ALTER TABLE transactions ADD COLUMN hours_since_event INTEGER NOT NULL DEFAULT 0"),
        ("transactions", "checkout_session_id", "ALTER TABLE transactions ADD COLUMN checkout_session_id TEXT"),
        ("recovery_cases", "risk_level", "ALTER TABLE recovery_cases ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'MEDIUM'"),
        ("recovery_cases", "risk_factors", "ALTER TABLE recovery_cases ADD COLUMN risk_factors TEXT NOT NULL DEFAULT '[]'"),
        ("recovery_cases", "recovery_priority", "ALTER TABLE recovery_cases ADD COLUMN recovery_priority REAL NOT NULL DEFAULT 0.0"),
        ("recovery_cases", "diagnosis_reason", "ALTER TABLE recovery_cases ADD COLUMN diagnosis_reason TEXT"),
        ("recovery_cases", "diagnosis_status", "ALTER TABLE recovery_cases ADD COLUMN diagnosis_status TEXT NOT NULL DEFAULT 'pending'"),
        ("recovery_cases", "diagnosed_at", "ALTER TABLE recovery_cases ADD COLUMN diagnosed_at TEXT"),
    ]
    for table, column, sql in migrations:
        if not _column_exists(conn, table, column):
            conn.execute(sql)
    conn.commit()


def seed_demo_data(conn: sqlite3.Connection) -> None:
    from app.services.risk_service import assess_transaction

    data_path = Path(settings.demo_data_path)
    if not data_path.is_absolute():
        data_path = Path(__file__).resolve().parents[1] / data_path
    with data_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    for row in rows:
        conn.execute(
            """
            INSERT INTO transactions (id, customer_id, customer_name, amount, currency,
                status, payment_method, failure_reason, created_at,
                retry_count, previous_successful_payments, customer_lifetime_value,
                hours_since_event, checkout_session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"], row["customer_id"], row["customer_name"], row["amount"],
                row["currency"], row["status"], row["payment_method"],
                row.get("failure_reason") or None, row["created_at"],
                int(row.get("retry_count", 0)),
                int(row.get("previous_successful_payments", 0)),
                row.get("customer_lifetime_value", "0.00"),
                int(row.get("hours_since_event", 0)),
                row.get("checkout_session_id") or None,
            ),
        )

        if row["status"] in {"failed", "abandoned"}:
            assessment = assess_transaction(row)
            txn_num = row["id"].split("-")[-1]
            conn.execute(
                """
                INSERT INTO recovery_cases
                    (id, transaction_id, risk_score, risk_level, risk_factors,
                     recovery_priority, root_cause, recommended_action, confidence,
                     status, amount_recovered, created_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 'pending_review', '0.00', ?)
                """,
                (
                    f"RC-{txn_num}",
                    row["id"],
                    assessment.risk_score,
                    assessment.risk_level,
                    json.dumps(assessment.risk_factors),
                    assessment.recovery_priority,
                    row["created_at"],
                ),
            )
    conn.commit()
