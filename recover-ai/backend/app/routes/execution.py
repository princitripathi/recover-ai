from fastapi import APIRouter, HTTPException

from app.schemas.execution import ExecuteRequest, ExecutionHistoryItem
from app.services.execution_service import execute_recovery_action, get_execution_history

router = APIRouter(prefix="/api/recovery-cases", tags=["execution"])


@router.post("/{case_id}/execute")
def run_execution(case_id: str, body: ExecuteRequest):
    """Execute a recovery action after policy gate verification.

    The backend independently verifies:
    - AI diagnosis exists
    - Policy decision = ALLOW
    - Action matches policy-approved action
    - Razorpay credentials are configured

    Only then calls Razorpay to create the payment link.
    """
    result = execute_recovery_action(case_id, body.action)
    return result


@router.get("/{case_id}/actions")
def list_execution_history(case_id: str):
    """Retrieve execution history for a recovery case."""
    history = get_execution_history(case_id)
    return {"case_id": case_id, "actions": history}
