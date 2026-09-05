"""AI Diagnosis service for RecoverAI.

Calls a local LLM (Ollama) to diagnose recovery cases and recommend
recovery actions. The LLM receives only transaction and risk data —
no secrets, no API keys, no ability to execute financial operations.

When the LLM is unavailable, returns AI_UNAVAILABLE status without crashing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import httpx

from app.config import settings
from app.database import get_connection
from app.schemas.diagnosis import (
    VALID_ACTIONS,
    VALID_ROOT_CAUSES,
    DiagnosisResult,
)

logger = logging.getLogger(__name__)

DIAGNOSIS_PROMPT = """You are diagnosing payment/revenue recovery cases for an e-commerce merchant.

Use ONLY the supplied transaction and risk information below. Do not invent facts.

Based on the data, provide:
1. root_cause: One of {root_causes}
2. recommended_action: One of {actions}
3. confidence: A number between 0.0 and 1.0 indicating your confidence
4. reason: A brief explanation of your diagnosis (1-3 sentences)
5. risk_factors: List the key factors that influenced your diagnosis

IMPORTANT:
- Financial actions (RETRY_PAYMENT, SEND_PAYMENT_LINK) will be checked by a separate deterministic policy engine before execution.
- Never claim an action was executed. You are only recommending.
- Return ONLY valid JSON, no other text.

Transaction and Risk Data:
{context}

Return your diagnosis as JSON with these exact keys:
{{
  "root_cause": "...",
  "recommended_action": "...",
  "confidence": 0.0,
  "reason": "...",
  "risk_factors": ["...", "..."]
}}"""


def _build_context(row: dict, risk_factors: list[str]) -> str:
    """Build the context string for the LLM prompt."""
    lines = [
        f"Transaction ID: {row['transaction_id']}",
        f"Customer: {row.get('customer_name', 'Unknown')}",
        f"Amount: {row.get('currency', 'INR')} {row.get('amount', 0)}",
        f"Transaction Status: {row.get('transaction_status', 'unknown')}",
        f"Payment Method: {row.get('payment_method', 'unknown')}",
        f"Failure Reason: {row.get('failure_reason', 'Not recorded')}",
        f"Retry Count: {row.get('retry_count', 0)}",
        f"Previous Successful Payments: {row.get('previous_successful_payments', 0)}",
        f"Customer Lifetime Value: {row.get('currency', 'INR')} {row.get('customer_lifetime_value', 0)}",
        f"Hours Since Event: {row.get('hours_since_event', 0)}",
        f"Risk Score: {row.get('risk_score', 0)}/100",
        f"Risk Level: {row.get('risk_level', 'UNKNOWN')}",
        f"Recovery Priority: {row.get('recovery_priority', 0)}",
        f"Risk Factors from Deterministic Engine: {'; '.join(risk_factors) if risk_factors else 'None'}",
    ]
    return "\n".join(lines)


def _parse_llm_response(raw: str) -> DiagnosisResult:
    """Parse and validate the LLM JSON response."""
    text = raw.strip()
    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return DiagnosisResult(
            root_cause="UNKNOWN_FAILURE",
            recommended_action="NO_ACTION",
            confidence=0.5,
            reason="Failed to parse AI response.",
            risk_factors=[],
        )

    root_cause = data.get("root_cause", "UNKNOWN_FAILURE")
    if root_cause not in VALID_ROOT_CAUSES:
        root_cause = "UNKNOWN_FAILURE"

    action = data.get("recommended_action", "NO_ACTION")
    if action not in VALID_ACTIONS:
        action = "NO_ACTION"

    confidence = float(data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    reason = str(data.get("reason", "No explanation provided."))
    risk_factors = data.get("risk_factors", [])
    if not isinstance(risk_factors, list):
        risk_factors = [str(risk_factors)]

    return DiagnosisResult(
        root_cause=root_cause,
        recommended_action=action,
        confidence=confidence,
        reason=reason,
        risk_factors=[str(f) for f in risk_factors],
    )


def diagnose_case(case_id: str) -> dict:
    """Run AI diagnosis on a recovery case.

    Returns a dict with diagnosis results or error status.
    Never raises exceptions to the caller for LLM failures.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT rc.*, t.customer_name, t.amount, t.currency, t.status AS transaction_status,
                   t.failure_reason, t.retry_count, t.previous_successful_payments,
                   t.customer_lifetime_value, t.hours_since_event, t.payment_method
            FROM recovery_cases rc
            JOIN transactions t ON t.id = rc.transaction_id
            WHERE rc.id = ?
            """,
            (case_id,),
        ).fetchone()

    if row is None:
        return {"diagnosis_status": "error", "error": "Recovery case not found"}

    data = dict(row)
    risk_factors_raw = data.get("risk_factors", "[]")
    try:
        risk_factors = json.loads(risk_factors_raw)
    except (json.JSONDecodeError, TypeError):
        risk_factors = []

    # Check if already diagnosed
    if data.get("diagnosis_status") == "completed":
        return {
            "diagnosis_status": "completed",
            "case_id": case_id,
            "root_cause": data.get("root_cause"),
            "recommended_action": data.get("recommended_action"),
            "confidence": data.get("confidence"),
            "reason": data.get("diagnosis_reason"),
            "risk_factors": risk_factors,
            "diagnosed_at": data.get("diagnosed_at"),
        }

    # Build context for LLM
    context = _build_context(data, risk_factors)
    prompt = DIAGNOSIS_PROMPT.format(
        root_causes=", ".join(VALID_ROOT_CAUSES),
        actions=", ".join(VALID_ACTIONS),
        context=context,
    )

    # Call LLM
    try:
        result = _call_ollama(prompt)
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        now = datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()
        _update_diagnosis_status(case_id, "ai_unavailable", now)
        return {
            "diagnosis_status": "ai_unavailable",
            "case_id": case_id,
            "error": f"AI service unavailable: {e}",
        }

    # Parse and validate
    try:
        diagnosis = _parse_llm_response(result)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Failed to parse LLM response: %s", e)
        now = datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()
        _update_diagnosis_status(case_id, "parse_error", now)
        return {
            "diagnosis_status": "parse_error",
            "case_id": case_id,
            "error": f"Failed to parse AI response: {e}",
        }

    # Persist diagnosis
    now = datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()
    _persist_diagnosis(
        case_id=case_id,
        root_cause=diagnosis.root_cause,
        recommended_action=diagnosis.recommended_action,
        confidence=diagnosis.confidence,
        reason=diagnosis.reason,
        diagnosed_at=now,
    )

    return {
        "diagnosis_status": "completed",
        "case_id": case_id,
        "root_cause": diagnosis.root_cause,
        "recommended_action": diagnosis.recommended_action,
        "confidence": diagnosis.confidence,
        "reason": diagnosis.reason,
        "risk_factors": diagnosis.risk_factors,
        "diagnosed_at": now,
    }


def _call_ollama(prompt: str) -> str:
    """Call Ollama API for LLM inference."""
    url = f"{settings.ollama_url}/api/generate"
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 512,
        },
    }
    with httpx.Client(timeout=settings.llm_timeout) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")


def _update_diagnosis_status(case_id: str, status: str, diagnosed_at: str) -> None:
    """Update only the diagnosis status (for error cases)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE recovery_cases SET diagnosis_status = ?, diagnosed_at = ? WHERE id = ?",
            (status, diagnosed_at, case_id),
        )
        conn.commit()


def _persist_diagnosis(
    case_id: str,
    root_cause: str,
    recommended_action: str,
    confidence: float,
    reason: str,
    diagnosed_at: str,
) -> None:
    """Persist a completed diagnosis to the database."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE recovery_cases
            SET root_cause = ?, recommended_action = ?, confidence = ?,
                diagnosis_reason = ?, diagnosis_status = 'completed', diagnosed_at = ?
            WHERE id = ?
            """,
            (root_cause, recommended_action, confidence, reason, diagnosed_at, case_id),
        )
        conn.commit()


def get_diagnosis(case_id: str) -> dict | None:
    """Retrieve stored diagnosis for a case. Returns None if not diagnosed."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM recovery_cases WHERE id = ?", (case_id,)
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    if data.get("diagnosis_status") != "completed":
        return None
    try:
        risk_factors = json.loads(data.get("risk_factors", "[]"))
    except (json.JSONDecodeError, TypeError):
        risk_factors = []
    return {
        "case_id": data["id"],
        "root_cause": data.get("root_cause"),
        "recommended_action": data.get("recommended_action"),
        "confidence": data.get("confidence"),
        "reason": data.get("diagnosis_reason"),
        "risk_factors": risk_factors,
        "diagnosis_status": data.get("diagnosis_status"),
        "diagnosed_at": data.get("diagnosed_at"),
    }
