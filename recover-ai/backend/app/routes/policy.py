from fastapi import APIRouter, HTTPException

from app.services.policy_service import evaluate_policy, get_policy_decision

router = APIRouter(prefix="/api/recovery-cases", tags=["policy"])


@router.post("/{case_id}/policy-check")
def run_policy_check(case_id: str):
    """Run deterministic policy check on a recovery case.

    Requires an existing AI diagnosis. Evaluates the recommended action
    against deterministic rules and returns ALLOW or BLOCK.
    """
    result = evaluate_policy(case_id)

    if result.get("decision") == "error":
        raise HTTPException(status_code=404, detail=result.get("error", "Case not found"))

    return result


@router.get("/{case_id}/policy")
def retrieve_policy_decision(case_id: str):
    """Retrieve the latest policy decision for a recovery case."""
    result = get_policy_decision(case_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Policy decision not found. Run POST /api/recovery-cases/{case_id}/policy-check first.",
        )
    return result
