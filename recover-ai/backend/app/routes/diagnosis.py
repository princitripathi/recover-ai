from fastapi import APIRouter, HTTPException

from app.schemas.diagnosis import DiagnosisResponse
from app.services.diagnosis_service import diagnose_case, get_diagnosis

router = APIRouter(prefix="/api/recovery-cases", tags=["diagnosis"])


@router.post("/{case_id}/diagnose")
def run_diagnosis(case_id: str):
    """Run AI diagnosis on a recovery case.

    The AI diagnoses the root cause and recommends a recovery action.
    It does NOT execute any financial operations.
    """
    result = diagnose_case(case_id)

    if result.get("diagnosis_status") == "error":
        raise HTTPException(status_code=404, detail=result.get("error", "Case not found"))

    return result


@router.get("/{case_id}/diagnosis")
def retrieve_diagnosis(case_id: str):
    """Retrieve the stored diagnosis for a recovery case."""
    result = get_diagnosis(case_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Diagnosis not found. Run POST /api/recovery-cases/{case_id}/diagnose first.",
        )
    return result
