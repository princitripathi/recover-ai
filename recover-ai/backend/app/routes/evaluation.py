"""Evaluation API for simulated batch evaluation."""
from fastapi import APIRouter
from app.services.evaluation_service import run_evaluation, get_latest_evaluation

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.post("/run")
def evaluation_run():
    """Run deterministic simulated batch evaluation."""
    result = run_evaluation()
    # Return shape required by spec
    return {
        "evaluation_type": result["evaluation_type"],
        "dataset_size": result["dataset_size"],
        "total_transactions": result.get("total_transactions", result["dataset_size"]),
        "total_revenue": result.get("total_revenue"),
        "revenue_at_risk": result["revenue_at_risk"],
        "recovery_cases": result.get("recovery_cases"),
        "eligible_cases": result.get("eligible_cases"),
        "policy_allowed": result["policy_allowed"],
        "policy_blocked": result["policy_blocked"],
        "recovery_attempts": result["recovery_attempts"],
        "successful_recoveries": result["successful_recoveries"],
        "failed_recoveries": result.get("failed_recoveries"),
        "amount_recovered": result["amount_recovered"],
        "recovery_rate": result["recovery_rate"],
        "case_recovery_rate": result["case_recovery_rate"],
        "baseline_recovered": result.get("baseline_recovered"),
        "baseline_note": result.get("baseline_note"),
        "created_at": result.get("created_at"),
        "id": result.get("id"),
    }


@router.get("/latest")
def evaluation_latest():
    """Retrieve latest evaluation run."""
    result = get_latest_evaluation()
    if result is None:
        return {"detail": "No evaluation runs yet. POST /api/evaluation/run to create one.", "evaluation_type": "NONE"}
    return {
        "evaluation_type": result["evaluation_type"],
        "dataset_size": result["dataset_size"],
        "total_transactions": result.get("total_transactions", result["dataset_size"]),
        "total_revenue": result.get("total_revenue"),
        "revenue_at_risk": result["revenue_at_risk"],
        "recovery_cases": result.get("recovery_cases"),
        "eligible_cases": result.get("eligible_cases"),
        "policy_allowed": result["policy_allowed"],
        "policy_blocked": result["policy_blocked"],
        "recovery_attempts": result["recovery_attempts"],
        "successful_recoveries": result["successful_recoveries"],
        "failed_recoveries": result.get("failed_recoveries"),
        "amount_recovered": result["amount_recovered"],
        "recovery_rate": result["recovery_rate"],
        "case_recovery_rate": result["case_recovery_rate"],
        "baseline_recovered": result.get("baseline_recovered"),
        "baseline_note": result.get("baseline_note"),
        "created_at": result.get("created_at"),
        "id": result.get("id"),
        "details": result.get("details"),
    }
