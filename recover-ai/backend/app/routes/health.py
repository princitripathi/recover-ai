from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "RecoverAI", "mode": "demo-synthetic"}
