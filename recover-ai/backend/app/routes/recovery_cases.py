from fastapi import APIRouter
from app.schemas.recovery_case import RecoveryCaseOut
from app.services.recovery_service import RecoveryService

router = APIRouter(prefix="/api/recovery-cases", tags=["recovery-cases"])
service = RecoveryService()


@router.get("", response_model=list[RecoveryCaseOut])
def list_recovery_cases():
    return service.list_cases()
